import asyncio
import hashlib
import io
import json
from uuid import uuid4

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_auth import USER_B, IsolatedStore, hosted_settings, install_auth_mock
from test_paper_extraction import decision, document
from test_paper_workflow import paper_store, pg_url, seed_pair, seed_paper, workflow_backend

from claim_trellis.api import create_app
from claim_trellis.ingestion import parse_document_bytes
from claim_trellis.paper_models import MappingDecision, PaperSourceMetadata, SourceLinkCreate
from claim_trellis.paper_references import marker_keys, normalized_doi, parse_references
from claim_trellis.paper_store import PaperWorkflowStore, WorkflowNotFound, digest
from claim_trellis.storage import LifecycleConflict

__all__ = ["paper_store", "pg_url", "workflow_backend"]
PAPER = "Model A improves accuracy [12, 17].\n\nReferences\n[12] Smith, J. (2024a). Advances in inference accuracy. Nature Machine Intelligence. doi:10.1234/accuracy.\n[17] Jones, A. (2025). Reducing the inference cost. Nature Machine Intelligence. doi:10.1234/cost."


@pytest.mark.parametrize(
    "marker,expected",
    [
        ("[12, 17]", {"n:12", "n:17"}),
        ("[12–14]", {"n:12", "n:13", "n:14"}),
        ("(Smith et al., 2024a; Jones, 2025)", {"a:smith:2024a", "a:jones:2025"}),
        ("Smith (2024)", {"a:smith:2024"}),
        ("[14-12]", set()),
        ("[1-9999]", set()),
        ("[unknown]", set()),
    ],
)
def test_bounded_numeric_and_author_year_keys(marker, expected):
    assert marker_keys(marker) == expected


@pytest.mark.parametrize("style", ["numeric", "author-year"])
def test_reference_offsets_multiline_metadata_and_stable_ids(style):
    prefix = "[12] " if style == "numeric" else ""
    text = (
        "A claim (Smith et al., 2024a).\n\nReferences\n"
        + prefix
        + "Smith, J. (2024a). Advances in inference accuracy.\nNature Machine Intelligence. https://doi.org/10.1234/accuracy.\n\n## Appendix\nIgnore this."
    )
    refs = parse_references(document(text))
    assert len(refs) == 1
    ref = refs[0]
    assert ref.raw_reference == text[ref.span.start : ref.span.end]
    assert ref.sha256 == hashlib.sha256(ref.raw_reference.encode()).hexdigest()
    assert ref.year == 2024 and ref.doi == "10.1234/accuracy"
    assert ref.title == "Advances in inference accuracy"
    assert "Appendix" not in ref.raw_reference
    assert ref.markers == (["[12]"] if style == "numeric" else ["(Smith, 2024a)"])
    assert [r.model_dump(exclude={"created_at"}) for r in parse_references(document(text))] == [
        r.model_dump(exclude={"created_at"}) for r in refs
    ]


def test_no_bibliography_heading_means_no_guessed_references():
    assert parse_references(document("[12] Smith, J. (2024). A study title.")) == []
    assert normalized_doi("https://doi.org/10.1234/ABC.") == "10.1234/abc"


def mapping_decision(source_id=None, action="confirm", **kwargs):
    return MappingDecision(
        decision=action,
        expected_state_revision=0,
        reviewer="Human R",
        notes="Read the original reference and uploaded source title page.",
        identity_confirmed=action == "confirm",
        source_document_id=source_id,
        idempotency_key=str(uuid4()),
        **kwargs,
    )


async def source_record(
    store, owner, project, doi="10.1234/accuracy", title="Advances in inference accuracy"
):
    parsed = parse_document_bytes("source.txt", b"The original source reports improved accuracy.")
    return await store.create_source(
        owner, project, str(uuid4()), parsed, PaperSourceMetadata(doi=doi, title=title, year=2024)
    )


async def setup_mapping(store, owner, text=PAPER):
    project, manuscript = await seed_paper(store, owner, text)
    candidate = (await store.extract_candidates(owner, project, manuscript.manuscript_id))[0]
    candidate = await store.decide_candidate(owner, project, candidate.candidate_id, decision())
    references = await store.parse_references(owner, project, manuscript.manuscript_id)
    return project, manuscript, candidate, references


@pytest.mark.asyncio
async def test_multi_source_links_roundtrip_human_gate_and_no_audits(paper_store):
    store, _, owner = paper_store
    project, manuscript, candidate, references = await setup_mapping(store, owner)
    s12 = await source_record(store, owner, project)
    s17 = await source_record(store, owner, project, "10.1234/cost", "Reducing the inference cost")
    assert await store.get(owner, project, s12.source_document_id, "source_document") == s12
    suggestions = await store.suggest_mappings(owner, project, candidate.candidate_id)
    assert len(suggestions.links) == 2
    assert all(link.status == "pending" for link in suggestions.links)
    assert {link.source_document_id for link in suggestions.links} == {
        s12.source_document_id,
        s17.source_document_id,
    }
    for link in suggestions.links:
        request = mapping_decision(link.source_document_id)
        confirmed = await store.decide_mapping(owner, project, link.link_id, request)
        assert confirmed.status == "confirmed" and confirmed.state_revision == 1
        assert await store.decide_mapping(owner, project, link.link_id, request) == confirmed
        with pytest.raises(LifecycleConflict):
            await store.decide_mapping(
                owner, project, link.link_id, request.model_copy(update={"notes": "Changed"})
            )
    assert all(
        link.status == "confirmed"
        for link in (await store.suggest_mappings(owner, project, candidate.candidate_id)).links
    )
    assert await store.parse_references(owner, project, manuscript.manuscript_id) == references
    assert await store.list_records(owner, project, "audit_link") == []
    events = await store.events(owner, project)
    assert len([e for e in events if e.event_type == "source_link.confirmed"]) == 2
    assert events[-1].payload["source_document_hash"] == s17.document_hash
    assert not any(e.event_type.startswith("audit.") for e in events)


@pytest.mark.asyncio
async def test_ambiguity_missing_sources_and_manual_identity(paper_store):
    store, _, owner = paper_store
    project, _, candidate, refs = await setup_mapping(
        store, owner, PAPER + "\n[12] Brown, J. (2024). A conflicting reference title."
    )
    s1, s2 = await source_record(store, owner, project), await source_record(store, owner, project)
    suggestions = await store.suggest_mappings(owner, project, candidate.candidate_id)
    assert len(suggestions.links) == 4  # two source matches + two unmapped references
    assert any("Ambiguous" in warning for warning in suggestions.warnings)
    assert any("Several sources" in warning for warning in suggestions.warnings)
    assert any("No metadata match" in warning for warning in suggestions.warnings)
    unmapped = next(link for link in suggestions.links if link.source_document_id is None)
    confirmed = await store.decide_mapping(
        owner, project, unmapped.link_id, mapping_decision(s1.source_document_id)
    )
    assert confirmed.source_document_id == s1.source_document_id
    duplicate = next(
        link for link in suggestions.links if link.source_document_id == s2.source_document_id
    )
    rejected = await store.decide_mapping(
        owner, project, duplicate.link_id, mapping_decision(action="reject")
    )
    assert rejected.status == "rejected"
    before = await store.events(owner, project)
    await store.suggest_mappings(owner, project, candidate.candidate_id)
    assert await store.events(owner, project) == before
    assert len(refs) == 3


@pytest.mark.asyncio
async def test_foreign_sources_unconfirmed_candidates_and_concurrent_reviews(paper_store):
    store, _, owner = paper_store
    project, _, candidate, refs = await setup_mapping(store, owner)
    s = await source_record(store, owner, project)
    link = (await store.suggest_mappings(owner, project, candidate.candidate_id)).links[0]
    other_project, _ = await seed_paper(store, owner)
    foreign = await source_record(store, owner, other_project)
    with pytest.raises(WorkflowNotFound):
        await store.decide_mapping(
            owner, project, link.link_id, mapping_decision(foreign.source_document_id)
        )
    with pytest.raises(WorkflowNotFound):
        await store.get(USER_B, project, s.source_document_id, "source_document")
    with pytest.raises(WorkflowNotFound):
        await store.decide_mapping(
            USER_B, project, link.link_id, mapping_decision(s.source_document_id)
        )
    results = await asyncio.gather(
        store.decide_mapping(owner, project, link.link_id, mapping_decision(s.source_document_id)),
        store.decide_mapping(owner, project, link.link_id, mapping_decision(action="reject")),
        return_exceptions=True,
    )
    assert sum(isinstance(result, LifecycleConflict) for result in results) == 1
    pending_project, pending_m = await seed_paper(store, owner, PAPER)
    pending = (await store.extract_candidates(owner, pending_project, pending_m.manuscript_id))[0]
    pending_refs = await store.parse_references(owner, pending_project, pending_m.manuscript_id)
    pending_source = await source_record(store, owner, pending_project)
    pending_link = await store.create_source_link(
        owner,
        pending_project,
        SourceLinkCreate(
            candidate_id=pending.candidate_id,
            reference_id=pending_refs[0].reference_id,
            idempotency_key="pending-link",
        ),
    )
    with pytest.raises(LifecycleConflict):
        await store.suggest_mappings(owner, pending_project, pending.candidate_id)
    with pytest.raises(LifecycleConflict):
        await store.decide_mapping(
            owner,
            pending_project,
            pending_link.link_id,
            mapping_decision(pending_source.source_document_id),
        )


@pytest.mark.parametrize(
    "patch",
    [
        {"identity_confirmed": False},
        {"source_document_id": None},
        {"reviewer": "   "},
        {"decision": "reject"},
    ],
)
def test_explicit_human_identity_is_mandatory(patch):
    with pytest.raises(ValidationError):
        MappingDecision.model_validate({**mapping_decision("source").model_dump(), **patch})


def upload_bytes(suffix):
    text = "The source reports improved accuracy."
    if suffix == "docx":
        doc = Document()
        doc.add_paragraph(text)
        buffer = io.BytesIO()
        doc.save(buffer)
        return buffer.getvalue()
    if suffix == "pdf":
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
        buffer = io.BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    return text.encode()


@pytest.mark.parametrize("suffix", ["txt", "md", "pdf", "docx"])
def test_source_upload_api_formats_owner_scope_and_replay(tmp_path, suffix):
    app = create_app(hosted_settings())
    install_auth_mock(app)
    app.state.paper_workflow_store = PaperWorkflowStore(path=tmp_path / "api.db")
    with TestClient(app) as client:
        a, b = {"Authorization": "Bearer token-a"}, {"Authorization": "Bearer token-b"}
        p = client.post(
            "/api/v1/projects", headers=a, json={"name": "P", "idempotency_key": "project-key"}
        ).json()["project_id"]
        base = "/api/v1/projects/" + p
        files = {"document": ("source." + suffix, upload_bytes(suffix), "application/octet-stream")}
        data = {
            "idempotency_key": "source-key",
            "metadata": json.dumps({"doi": "10.1234/accuracy", "year": 2024}),
        }
        assert client.post(base + "/sources", headers=b, files=files, data=data).status_code == 404
        response = client.post(base + "/sources", headers=a, files=files, data=data)
        assert response.status_code == 201
        record = response.json()
        assert record["blocks"] and record["parser_version"] == "structured-document-v2"
        assert "improved accuracy" in record["text"]
        assert client.post(base + "/sources", headers=a, files=files, data=data).json() == record
        assert (
            client.post(
                base + "/sources", headers=a, files=files, data={**data, "metadata": "{}"}
            ).status_code
            == 409
        )
        assert (
            client.get(base + "/sources/" + record["source_document_id"], headers=b).status_code
            == 404
        )
        assert client.get(base + "/sources", headers=a).json() == [record]
        assert (
            client.post(
                base + "/sources",
                headers=a,
                files=files,
                data={**data, "metadata": '{"owner_user_id":"forged"}'},
            ).status_code
            == 422
        )
        app.state.settings.max_upload_bytes = 3
        assert client.post(base + "/sources", headers=a, files=files, data=data).status_code == 422


@pytest.mark.asyncio
async def test_p1_1_serialized_defaults_remain_replay_compatible(paper_store):
    store, _, owner = paper_store
    project, _, _, reference, link = await seed_pair(store, owner)
    events = await store.events(owner, project)
    for kind, record, identifier, added in (
        ("reference", reference, reference.reference_id, "parser_version"),
        ("source_link", link, link.link_id, "suggestion_reasons"),
    ):
        legacy = record.model_dump(mode="json", exclude={added})
        async with store.transaction() as conn:
            await conn.execute(
                "UPDATE paper_workflow_records SET record_json=?,creation_sha256=? WHERE record_id=? AND owner_user_id=?",
                (
                    legacy,
                    digest({k: v for k, v in legacy.items() if k != "created_at"}),
                    identifier,
                    owner,
                ),
            )
        assert (await store.create_records(owner, project, kind, [record]))[0] == record
    assert await store.events(owner, project) == events


@pytest.mark.asyncio
async def test_title_suggestion_does_not_override_conflicting_doi(paper_store):
    store, _, owner = paper_store
    text = "Model A improves accuracy (Smith et al., 2024a).\n\nReferences\nSmith, J. (2024a). Advances in inference accuracy. Nature. doi:10.1234/accuracy."
    project, _, candidate, refs = await setup_mapping(store, owner, text)
    wrong = await source_record(store, owner, project, "10.1234/wrong")
    suggestions = await store.suggest_mappings(owner, project, candidate.candidate_id)
    assert len(suggestions.links) == 1 and suggestions.links[0].source_document_id is None
    title_only = await source_record(store, owner, project, None)
    suggestions = await store.suggest_mappings(owner, project, candidate.candidate_id)
    matches = [link for link in suggestions.links if link.source_document_id]
    assert len(matches) == 1 and matches[0].source_document_id == title_only.source_document_id
    assert wrong.source_document_id != matches[0].source_document_id
    assert matches[0].suggestion_reasons == ["matching_supplied_title"]
    assert refs[0].markers == ["(Smith, 2024a)"]


@pytest.mark.asyncio
async def test_unknown_or_excessive_markers_remain_unresolved(paper_store):
    store, _, owner = paper_store
    project, _, candidate, _ = await setup_mapping(
        store,
        owner,
        "Model A improves accuracy [1-9999].\n\nReferences\n[1] Smith, J. (2024). A source title.",
    )
    result = await store.suggest_mappings(owner, project, candidate.candidate_id)
    assert result.links == []
    assert any("could not be resolved" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_oversized_extraction_and_bibliography_fail_before_persistence(paper_store):
    store, _, owner = paper_store
    text = "Model A improves accuracy [12]. " * 2001
    project, manuscript = await seed_paper(store, owner, text)
    before = await store.events(owner, project)
    with pytest.raises(ValueError, match="2,000 candidates"):
        await store.extract_candidates(owner, project, manuscript.manuscript_id)
    assert await store.list_records(owner, project, "candidate") == []
    assert await store.events(owner, project) == before
    text = (
        "Model A improves accuracy [12].\n\nReferences\n"
        + "[12] Smith, J. (2024). A source title.\n" * 2001
    )
    project, manuscript = await seed_paper(store, owner, text)
    before = await store.events(owner, project)
    with pytest.raises(ValueError, match="2,000 bibliography"):
        await store.parse_references(owner, project, manuscript.manuscript_id)
    assert await store.list_records(owner, project, "reference") == []
    assert await store.events(owner, project) == before


@pytest.mark.parametrize("style", ["numeric", "author-year"])
def test_backend_prototype_api_flow_stops_before_audit_execution(tmp_path, style):
    app = create_app(hosted_settings())
    install_auth_mock(app)
    app.state.paper_workflow_store = PaperWorkflowStore(path=tmp_path / "api.db")
    audits = IsolatedStore()
    app.state.lifecycle_store = audits
    with TestClient(app) as client:
        a, b = {"Authorization": "Bearer token-a"}, {"Authorization": "Bearer token-b"}
        p = client.post(
            "/api/v1/projects", headers=a, json={"name": "P", "idempotency_key": "api-project"}
        ).json()["project_id"]
        base = "/api/v1/projects/" + p
        text = (
            PAPER
            if style == "numeric"
            else "Model A improves accuracy (Smith et al., 2024a).\n\nReferences\nSmith, J. (2024a). Advances in inference accuracy. Nature. doi:10.1234/accuracy."
        )
        m = client.post(
            base + "/manuscripts",
            headers=a,
            json={"filename": "p.txt", "text": text, "idempotency_key": "manuscript-key"},
        ).json()["manuscript_id"]
        mid = base + "/manuscripts/" + m
        c = client.post(mid + "/extract-candidates", headers=a).json()[0]
        cid = base + "/candidates/" + c["candidate_id"]
        assert client.post(cid + "/suggest-mappings", headers=a).status_code == 409
        assert (
            client.post(
                cid + "/decisions", headers=a, json=decision().model_dump(mode="json")
            ).status_code
            == 200
        )
        refs = client.post(mid + "/parse-references", headers=a)
        assert refs.status_code == 200 and refs.json()
        data = {"idempotency_key": "uploaded-source", "metadata": '{"doi":"10.1234/accuracy"}'}
        source = client.post(
            base + "/sources",
            headers=a,
            files={"document": ("s.txt", b"A source text with results.", "text/plain")},
            data=data,
        ).json()
        links = client.post(cid + "/suggest-mappings", headers=a)
        assert links.status_code == 200
        link = next(item for item in links.json()["links"] if item["source_document_id"])
        route = base + "/source-links/" + link["link_id"] + "/decisions"
        body = mapping_decision(source["source_document_id"]).model_dump(mode="json")
        assert client.post(route, headers=b, json=body).status_code == 404
        assert (
            client.post(route, headers=a, json={**body, "identity_confirmed": False}).status_code
            == 422
        )
        confirmed = client.post(route, headers=a, json=body)
        assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
        assert client.post(route, headers=a, json=body).json() == confirmed.json()
        events = client.get(base + "/events", headers=a).json()
        assert len([e for e in events if e["event_type"] == "source_link.confirmed"]) == 1
        assert not audits.audits
