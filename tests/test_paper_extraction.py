import asyncio
import hashlib
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_auth import USER_B, hosted_settings, install_auth_mock
from test_paper_workflow import paper_store, pg_url, seed_paper, workflow_backend

from claim_trellis.api import create_app
from claim_trellis.document_blocks import text_blocks
from claim_trellis.paper_extraction import extract_candidates
from claim_trellis.paper_models import CandidateDecision, Manuscript
from claim_trellis.paper_store import PaperWorkflowStore, WorkflowNotFound
from claim_trellis.storage import LifecycleConflict

__all__ = ["paper_store", "pg_url", "workflow_backend"]
RUBRIC = {"atomic": True, "faithful": True, "necessary_context": True}


def document(text):
    return Manuscript(
        manuscript_id="manuscript",
        project_id="project",
        filename="p.txt",
        media_type="text/plain",
        text=text,
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        blocks=text_blocks(text),
        parser_version="test",
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "Model A improves accuracy and reduces inference time [12].",
            ["Model A improves accuracy", "reduces inference time"],
        ),
        (
            "Model A improves accuracy on cats and dogs [12].",
            ["Model A improves accuracy on cats and dogs"],
        ),
        (
            "Model A improves accuracy (on cats and reduces risk) [12].",
            ["Model A improves accuracy (on cats and reduces risk)"],
        ),
        (
            'Model A uses "improves accuracy; reduces risk" [12].',
            ['Model A uses "improves accuracy; reduces risk"'],
        ),
        (
            "Model A improves accuracy; Model B reduces risk [12].",
            ["Model A improves accuracy", "Model B reduces risk"],
        ),
        ("Smith (2024) improves accuracy.", ["Smith (2024) improves accuracy"]),
        ("Model A improves accuracy (Smith et al., 2024a).", ["Model A improves accuracy"]),
        ("No citations or assumptions.", []),
    ],
)
def test_exact_clause_spans_without_synthetic_subjects(text, expected):
    rows = extract_candidates(document(text))
    assert [row.original_span for row in rows] == expected
    for row in rows:
        assert row.original_span == text[row.exact_span_start : row.exact_span_end]
        assert row.source_sentence == text[row.sentence_span.start : row.sentence_span.end]
        assert row.status == "pending" and row.confirmed_claim is None
        assert row.sha256 == hashlib.sha256(row.original_span.encode()).hexdigest()


def test_unicode_repetition_and_bibliography_exclusion():
    text = "α Model A improves accuracy [12]. Model A improves accuracy [12].\n\n## References\n[12] Smith. A study. 2024."
    a, b = extract_candidates(document(text))
    assert a.candidate_id != b.candidate_id
    assert a.exact_span_start == 0 and b.exact_span_start == text.index("Model A", 6)
    assert [a.candidate_id, b.candidate_id] == [
        r.candidate_id for r in extract_candidates(document(text))
    ]


@pytest.mark.parametrize(
    "patch",
    [
        {"rubric": None},
        {"rubric": {**RUBRIC, "faithful": False}},
        {"confirmed_claim": "Generated claim"},
        {"decision": "edit"},
        {"reviewer": "   "},
        {"owner_user_id": "spoofed"},
    ],
)
def test_human_gate_fails_closed(patch):
    with pytest.raises(ValidationError):
        CandidateDecision.model_validate(
            {
                "decision": "confirm",
                "expected_state_revision": 0,
                "reviewer": "R",
                "notes": "Checked",
                "rubric": RUBRIC,
                "idempotency_key": "review-key",
                **patch,
            }
        )


def decision(action="confirm", **kwargs):
    return CandidateDecision(
        decision=action,
        expected_state_revision=0,
        reviewer="Human R",
        notes="Read the original sentence and citation.",
        rubric=RUBRIC if action != "reject" else None,
        idempotency_key=str(uuid4()),
        **kwargs,
    )


@pytest.mark.asyncio
async def test_edit_preserves_span_events_and_extraction_replay(paper_store):
    store, _, owner = paper_store
    project, manuscript = await seed_paper(
        store, owner, "Model A improves accuracy and reduces inference time [12]."
    )
    initial = await store.extract_candidates(owner, project, manuscript.manuscript_id)
    second = initial[1]
    request = decision("edit", confirmed_claim="Model A reduces inference time")
    updated = await store.decide_candidate(owner, project, second.candidate_id, request)
    assert updated.original_span == "reduces inference time"
    assert updated.confirmed_claim == "Model A reduces inference time"
    assert updated.state_revision == 1
    assert await store.decide_candidate(owner, project, second.candidate_id, request) == updated
    replay = await store.extract_candidates(owner, project, manuscript.manuscript_id)
    assert replay[1] == updated
    events = await store.events(owner, project)
    assert events[-1].payload["original_span"] == second.original_span
    assert events[-1].payload["request"]["rubric"] == RUBRIC
    assert events[-1].payload["confirmed_claim"] == updated.confirmed_claim
    assert len([e for e in events if e.event_type == "candidate.confirmed"]) == 1
    with pytest.raises(LifecycleConflict):
        await store.decide_candidate(
            owner, project, second.candidate_id, request.model_copy(update={"notes": "Changed"})
        )
    with pytest.raises(WorkflowNotFound):
        await store.decide_candidate(USER_B, project, second.candidate_id, request)
    rejected = await store.decide_candidate(
        owner, project, initial[0].candidate_id, decision("reject")
    )
    assert rejected.confirmed_claim is None and rejected.status == "rejected"


@pytest.mark.asyncio
async def test_one_concurrent_human_decision_wins(paper_store):
    store, _, owner = paper_store
    project, manuscript = await seed_paper(store, owner)
    candidate = (await store.extract_candidates(owner, project, manuscript.manuscript_id))[0]
    results = await asyncio.gather(
        store.decide_candidate(owner, project, candidate.candidate_id, decision()),
        store.decide_candidate(owner, project, candidate.candidate_id, decision("reject")),
        return_exceptions=True,
    )
    assert sum(isinstance(result, LifecycleConflict) for result in results) == 1
    assert (
        len(
            [e for e in await store.events(owner, project) if e.event_type.startswith("candidate.")]
        )
        == 2
    )
    with pytest.raises(LifecycleConflict):
        await store.decide_candidate(owner, project, candidate.candidate_id, decision())


def test_extraction_api_and_review_validation(tmp_path):
    app = create_app(hosted_settings())
    install_auth_mock(app)
    app.state.paper_workflow_store = PaperWorkflowStore(path=tmp_path / "api.db")
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer token-a"}
        p = client.post(
            "/api/v1/projects",
            headers=headers,
            json={"name": "P", "idempotency_key": "project-key"},
        ).json()["project_id"]
        base = "/api/v1/projects/" + p
        m = client.post(
            base + "/manuscripts",
            headers=headers,
            json={
                "filename": "p.txt",
                "text": "Model A improves accuracy [12].",
                "idempotency_key": "manuscript-key",
            },
        ).json()["manuscript_id"]
        route = base + "/manuscripts/" + m + "/extract-candidates"
        assert client.post(route, headers={"Authorization": "Bearer token-b"}).status_code == 404
        rows = client.post(route, headers=headers)
        assert rows.status_code == 200
        review_route = base + "/candidates/" + rows.json()[0]["candidate_id"] + "/decisions"
        body = decision().model_dump(mode="json")
        assert (
            client.post(review_route, headers=headers, json={**body, "rubric": None}).status_code
            == 422
        )
        response = client.post(review_route, headers=headers, json=body)
        assert response.status_code == 200
        assert response.json()["confirmed_claim"] == response.json()["original_span"]
