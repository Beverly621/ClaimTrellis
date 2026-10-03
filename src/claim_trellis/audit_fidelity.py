from __future__ import annotations

from typing import Any

from claim_trellis.deterministic import run_deterministic_checks
from claim_trellis.evidence_sets import evidence_text, revision_evidence
from claim_trellis.models import ClaimAudit, JudgmentResult, Proposal, RevisionRequest


def initial_events(audit: ClaimAudit) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = [
        (
            "document.parsed",
            {
                "parser_version": audit.provenance.parser_version,
                "blocks": [b.model_dump(mode="json") for b in audit.source_blocks],
            },
        ),
        ("retrieval.started", {"retrieval_version": audit.provenance.retrieval_version}),
        ("retrieval.completed", {"candidate_count": len(audit.candidates)}),
    ]
    events.extend(
        ("candidate.created", candidate.model_dump(mode="json")) for candidate in audit.candidates
    )
    events.append(
        (
            "evidence.selected",
            {
                "evidence_set": audit.evidence_set.model_dump(mode="json")
                if audit.evidence_set
                else None
            },
        )
    )
    return events


def complete_evidence_revision(
    audit: ClaimAudit, request: RevisionRequest, judgment: JudgmentResult | None, policy: Proposal
) -> dict[str, Any] | None:
    selected = revision_evidence(audit, request)
    previous = audit.evidence_set
    changed = None
    if request.selected_passage_ids is not None and selected is not None:
        checks = run_deterministic_checks(
            audit.claim,
            evidence_text(selected),
            audit.requested_quote,
            citation=audit.citation,
            access_tier=audit.source.access_tier,
        )
        if previous is None or previous.sha256 != selected.sha256:
            changed = {
                "old": [p.passage_id for p in previous.passages]
                if previous
                else [audit.selected_passage.passage_id]
                if audit.selected_passage
                else [],
                "new": [p.passage_id for p in selected.passages],
                "old_hash": previous.sha256 if previous else None,
                "new_hash": selected.sha256,
                "reviewer": request.reviewer,
            }
        audit.evidence_set = selected
        audit.selected_passage = selected.passages[0]
        audit.deterministic_checks = checks
    audit.provenance = audit.provenance.model_copy(
        update={
            "judgment_provider": judgment.provider if judgment else None,
            "question_set_version": judgment.question_set_version if judgment else "not-run",
            "policy_version": policy.policy_version,
            "check_set_version": audit.deterministic_checks.check_set_version,
            "requested_model": judgment.requested_model if judgment else None,
            "resolved_model": judgment.resolved_model if judgment else None,
            "evidence_set_hash": selected.sha256 if selected else None,
        }
    )
    return changed
