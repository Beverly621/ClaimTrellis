"""The same owner-scoped workflow contract runs on SQLite and real PostgreSQL."""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from test_auth import USER_A, USER_B, hosted_settings, install_auth_mock
from test_postgres_store import opened, pg_url
from test_storage import example_audit

from claim_trellis.api import create_app
from claim_trellis.paper_models import (
    CandidateCreate,
    ExactSpan,
    ManuscriptCreate,
    ProjectAuditLink,
    ProjectCreate,
    ReferenceCreate,
    SourceLinkCreate,
)
from claim_trellis.paper_store import PaperWorkflowStore, WorkflowNotFound
from claim_trellis.storage import AuditStore, LifecycleConflict
from claim_trellis.store import LOCAL_USER_ID

__all__ = ["pg_url"]
TEXT = "Model A improves accuracy [12].\n\nReferences\n[12] Smith. A study. 2024."


@pytest.fixture(params=["sqlite", "postgres"])
def workflow_backend(request):
    return request.getfixturevalue("pg_url") if request.param == "postgres" else None


@pytest_asyncio.fixture
async def paper_store(workflow_backend, tmp_path):
    if workflow_backend:
        audit_store = await opened(workflow_backend)
        store = PaperWorkflowStore(pool=audit_store.pool)
        yield store, audit_store, USER_A
        await audit_store.close()
    else:
        path = tmp_path / "audits.db"
        audit_store = AuditStore(path)
        yield PaperWorkflowStore(path=path), audit_store, LOCAL_USER_ID


async def seed_paper(store, owner, text=TEXT):
    project = await store.create_project(
        owner, ProjectCreate(name="Test", idempotency_key=str(uuid4()))
    )
    manuscript = await store.create_manuscript(
        owner,
        project.project_id,
        ManuscriptCreate(filename="paper.txt", text=text, idempotency_key="manuscript-test"),
    )
    return project.project_id, manuscript


async def seed_pair(store, owner):
    project, manuscript = await seed_paper(store, owner)
    candidate = await store.create_candidate(
        owner,
        project,
        manuscript.manuscript_id,
        CandidateCreate(
            idempotency_key="candidate-test",
            sentence_span=ExactSpan(start=0, end=30),
            clause_span=ExactSpan(start=0, end=25),
            citation_markers=["[12]"],
        ),
    )
    start = TEXT.index("[12] Smith")
    reference = await store.create_reference(
        owner,
        project,
        manuscript.manuscript_id,
        ReferenceCreate(
            idempotency_key="reference-test",
            span=ExactSpan(start=start, end=len(TEXT)),
            markers=["[12]"],
            year=2024,
        ),
    )
    link = await store.create_source_link(
        owner,
        project,
        SourceLinkCreate(
            idempotency_key="source-link-test",
            candidate_id=candidate.candidate_id,
            reference_id=reference.reference_id,
        ),
    )
    return project, manuscript, candidate, reference, link


@pytest.mark.asyncio
async def test_all_contracts_roundtrip_and_events(paper_store):
    store, audit_store, owner = paper_store
    project, manuscript, candidate, reference, link = await seed_pair(store, owner)
    audit = example_audit().model_copy(update={"audit_id": str(uuid4())})
    if owner == LOCAL_USER_ID:
        audit_store.save(audit)
    else:
        await audit_store.save(owner, audit)
    audit_link = ProjectAuditLink(
        audit_link_id=str(uuid4()),
        project_id=project,
        claim_source_link_id=link.link_id,
        audit_id=audit.audit_id,
    )
    await store.create_records(owner, project, "audit_link", [audit_link])
    for kind, record, identifier in (
        ("manuscript", manuscript, manuscript.manuscript_id),
        ("candidate", candidate, candidate.candidate_id),
        ("reference", reference, reference.reference_id),
        ("source_link", link, link.link_id),
        ("audit_link", audit_link, audit_link.audit_link_id),
    ):
        assert await store.get(owner, project, identifier, kind) == record
        assert await store.list_records(owner, project, kind) == [record]
    assert [event.event_type for event in await store.events(owner, project)] == [
        "project.created",
        "manuscript.created",
        "candidate.created",
        "reference.created",
        "source_link.created",
        "audit_link.created",
    ]
    assert len(await store.events(owner, project, limit=2, offset=2)) == 2


@pytest.mark.asyncio
async def test_owner_and_project_isolation(paper_store):
    store, _, owner = paper_store
    project, manuscript, candidate, reference, _ = await seed_pair(store, owner)
    for operation in (
        store.get_project(USER_B, project),
        store.events(USER_B, project),
        store.get(USER_B, project, manuscript.manuscript_id, "manuscript"),
        store.list_records(USER_B, project, "candidate"),
        store.create_manuscript(
            USER_B,
            project,
            ManuscriptCreate(filename="x.txt", text="private", idempotency_key="other-owner"),
        ),
    ):
        with pytest.raises(WorkflowNotFound):
            await operation
    assert project not in [p.project_id for p in await store.list_projects(USER_B)]
    second, _ = await seed_paper(store, owner)
    with pytest.raises(WorkflowNotFound):
        await store.create_source_link(
            owner,
            second,
            SourceLinkCreate(
                candidate_id=candidate.candidate_id,
                reference_id=reference.reference_id,
                idempotency_key="cross-project",
            ),
        )
    foreign, foreign_m = await seed_paper(store, USER_B)
    assert foreign != project
    with pytest.raises(WorkflowNotFound):
        await store.get(owner, project, foreign_m.manuscript_id, "manuscript")
    third = await store.create_manuscript(
        owner,
        project,
        ManuscriptCreate(filename="other.txt", text=TEXT, idempotency_key="second-manuscript"),
    )
    other_ref = await store.create_reference(
        owner,
        project,
        third.manuscript_id,
        ReferenceCreate(span=reference.span, markers=["[12]"], idempotency_key="other-reference"),
    )
    with pytest.raises(LifecycleConflict):
        await store.create_source_link(
            owner,
            project,
            SourceLinkCreate(
                candidate_id=candidate.candidate_id,
                reference_id=other_ref.reference_id,
                idempotency_key="cross-manuscript",
            ),
        )


@pytest.mark.asyncio
async def test_idempotency_and_concurrent_creation(paper_store):
    store, _, owner = paper_store
    request = ProjectCreate(name="Concurrent", idempotency_key=str(uuid4()))
    a, b = await asyncio.gather(
        store.create_project(owner, request), store.create_project(owner, request)
    )
    assert a == b
    assert len(await store.events(owner, a.project_id)) == 1
    with pytest.raises(LifecycleConflict):
        await store.create_project(owner, request.model_copy(update={"name": "Changed"}))
    item = ManuscriptCreate(filename="x.txt", text=TEXT, idempotency_key="same-manuscript")
    m = await store.create_manuscript(owner, a.project_id, item)
    assert await store.create_manuscript(owner, a.project_id, item) == m
    with pytest.raises(LifecycleConflict):
        await store.create_manuscript(
            owner, a.project_id, item.model_copy(update={"text": "Different"})
        )
    assert len(await store.events(owner, a.project_id)) == 2


@pytest.mark.asyncio
async def test_forged_spans_and_atomic_batch_rollback(paper_store):
    store, _, owner = paper_store
    project, _, candidate, _, _ = await seed_pair(store, owner)
    valid = candidate.model_copy(update={"candidate_id": str(uuid4())})
    bad = candidate.model_copy(
        update={"candidate_id": str(uuid4()), "original_span": "AI-generated rewrite"}
    )
    events = await store.events(owner, project)
    with pytest.raises(ValueError):
        await store.create_records(owner, project, "candidate", [valid, bad])
    assert await store.events(owner, project) == events
    with pytest.raises(WorkflowNotFound):
        await store.get(owner, project, valid.candidate_id, "candidate")
    with pytest.raises(WorkflowNotFound):
        await store.create_records(
            owner,
            project,
            "audit_link",
            [
                ProjectAuditLink(
                    audit_link_id=str(uuid4()),
                    project_id=project,
                    claim_source_link_id="unknown",
                    audit_id="unknown",
                )
            ],
        )


def test_project_api_auth_scope_and_idempotency(tmp_path):
    app = create_app(hosted_settings())
    install_auth_mock(app)
    app.state.paper_workflow_store = PaperWorkflowStore(path=tmp_path / "api.db")
    with TestClient(app) as client:
        a, b = {"Authorization": "Bearer token-a"}, {"Authorization": "Bearer token-b"}
        body = {"name": "Paper", "idempotency_key": "api-project"}
        assert client.post("/api/v1/projects", json=body).status_code == 401
        assert (
            client.post(
                "/api/v1/projects", headers=a, json={**body, "owner_user_id": USER_B}
            ).status_code
            == 422
        )
        created = client.post("/api/v1/projects", headers=a, json=body)
        assert created.status_code == 201
        assert client.post("/api/v1/projects", headers=a, json=body).json() == created.json()
        base = "/api/v1/projects/" + created.json()["project_id"]
        assert client.get(base, headers=b).status_code == 404
        assert client.get(base + "/events", headers=b).status_code == 404
        assert client.get("/api/v1/projects", headers=b).json() == []
        assert client.get(base + "/events?limit=201", headers=a).status_code == 422
        request = {"filename": "paper.txt", "text": TEXT, "idempotency_key": "api-manuscript"}
        assert client.post(base + "/manuscripts", headers=b, json=request).status_code == 404
        m = client.post(base + "/manuscripts", headers=a, json=request)
        assert m.status_code == 201
        assert (
            client.get(base + "/manuscripts/" + m.json()["manuscript_id"], headers=a).json()
            == m.json()
        )
