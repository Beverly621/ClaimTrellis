"""Fail the engineering acceptance gate on any broken Matrix-to-source link."""

import hashlib
from typing import Any

from claim_trellis.evidence_sets import make_evidence_set
from claim_trellis.models import ClaimAudit
from claim_trellis.paper_store import digest


def verify_trace(
    *,
    row: dict[str, Any],
    manuscript: dict[str, Any],
    candidate: dict[str, Any],
    reference: dict[str, Any],
    source: dict[str, Any],
    item: dict[str, Any],
    project_events: list[dict[str, Any]],
    audit: dict[str, Any],
    proposals: list[dict[str, Any]],
    audit_events: list[dict[str, Any]],
    revisions: list[dict[str, Any]],
) -> dict[str, str | int]:
    parsed = ClaimAudit.model_validate(audit)
    snapshot = item["snapshot"]
    assert row["audit_id"] == audit["audit_id"] == item["audit_id"]
    assert row["candidate_id"] == candidate["candidate_id"] == snapshot["candidate_id"]
    assert candidate["manuscript_id"] == manuscript["manuscript_id"] == row["manuscript_id"]
    original = manuscript["text"][candidate["exact_span_start"] : candidate["exact_span_end"]]
    assert original == candidate["original_span"] == row["original_span"]
    assert (
        hashlib.sha256(original.encode()).hexdigest()
        == candidate["sha256"]
        == snapshot["candidate_sha256"]
    )
    assert (
        candidate["confirmed_claim"]
        == snapshot["confirmed_claim"]
        == audit["claim"]
        == row["confirmed_claim"]
    )
    assert snapshot["candidate_state_revision"] == candidate["state_revision"]
    assert reference["reference_id"] == snapshot["reference_id"] == row["reference_id"]
    assert (
        manuscript["text"][reference["span"]["start"] : reference["span"]["end"]]
        == reference["raw_reference"]
        == row["citation"]
    )
    assert (
        hashlib.sha256(reference["raw_reference"].encode()).hexdigest()
        == reference["sha256"]
        == snapshot["reference_sha256"]
    )
    assert (
        source["source_document_id"] == snapshot["source_document_id"] == row["source_document_id"]
    )
    assert (
        hashlib.sha256(source["text"].encode()).hexdigest()
        == source["document_hash"]
        == snapshot["source_document_hash"]
        == audit["source"]["content_sha256"]
    )
    assert digest(source["metadata"]) == snapshot["source_metadata_hash"]
    assert digest(source["blocks"]) == snapshot["source_blocks_hash"]
    assert digest(snapshot) == item["input_snapshot_hash"] == row["input_snapshot_hash"]
    identity = next(e for e in project_events if e["event_id"] == snapshot["identity_event_id"])
    assert (
        identity["event_type"] == "source_link.confirmed" and identity["record_id"] == row["row_id"]
    )
    assert identity["payload"]["source_document_hash"] == source["document_hash"]
    assert identity["payload"]["request"]["identity_confirmed"] is True
    assert identity["payload"]["request"]["reviewer"]
    human_claim = next(
        e
        for e in project_events
        if e["event_type"] == "candidate.confirmed" and e["record_id"] == candidate["candidate_id"]
    )
    assert all(human_claim["payload"]["request"]["rubric"].values())
    assert human_claim["payload"]["request"]["reviewer"]
    for result in parsed.candidates:
        passage = result.passage
        assert source["text"][passage.start_char : passage.end_char] == passage.text
        assert hashlib.sha256(passage.text.encode()).hexdigest() == passage.sha256
    assert parsed.evidence_set and parsed.candidates
    assert (
        make_evidence_set(parsed.evidence_set.passages).sha256
        == parsed.evidence_set.sha256
        == parsed.provenance.evidence_set_hash
    )
    candidate_ids = {c.passage.passage_id for c in parsed.candidates}
    assert all(p.passage_id in candidate_ids for p in parsed.evidence_set.passages)
    assert parsed.deterministic_checks.check_set_version == "deterministic-v2"
    assert parsed.provenance.retrieval_version == "lexical-evidence-v2"
    assert parsed.judgment_result and parsed.judgment_result.raw_answers
    assert parsed.judgment_result.requested_model == parsed.provenance.requested_model
    assert parsed.judgment_result.resolved_model == parsed.provenance.resolved_model
    assert parsed.judgment_result.question_set_version == parsed.provenance.question_set_version
    assert parsed.proposal.policy_version == parsed.provenance.policy_version == "fail-closed-v2"
    assert parsed.proposal.reasons and not parsed.proposal.auto_accepted
    assert [p["version"] for p in proposals] == list(range(1, len(proposals) + 1))
    assert proposals[-1]["proposal_id"] == parsed.current_proposal_id
    assert proposals[-1]["judgment"] == parsed.judgment_result.model_dump(mode="json")
    for proposal in proposals:
        assert (
            proposal["provenance"] and proposal["evidence_set"] and proposal["deterministic_checks"]
        )
        assert proposal["policy"]["reasons"] and not proposal["policy"]["auto_accepted"]
    assert parsed.human_review and parsed.human_review.reviewer
    assert parsed.human_review.proposal_id == parsed.current_proposal_id
    event_types = {e["event_type"] for e in audit_events}
    assert {
        "document.parsed",
        "retrieval.completed",
        "evidence.selected",
        "proposal.created",
        "review.accepted",
    } <= event_types
    if revisions:
        assert {"revision.completed", "evidence.selection.changed"} <= event_types
        assert all(r["status"] == "revision_completed" for r in revisions)
        assert parsed.current_proposal_version > 1
    return {
        "traceability_gate": "passed",
        "proposal_versions": len(proposals),
        "revisions": len(revisions),
        "requested_model": parsed.provenance.requested_model,
        "resolved_model": parsed.provenance.resolved_model,
        "question_set_version": parsed.provenance.question_set_version,
        "retrieval_version": parsed.provenance.retrieval_version,
    }
