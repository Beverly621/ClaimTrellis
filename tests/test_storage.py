from claim_trellis.models import (
    ClaimAudit,
    DeterministicChecks,
    HumanDecision,
    HumanReview,
    Proposal,
    ProposalStatus,
    Provenance,
    SourceMetadata,
)
from claim_trellis.storage import AuditStore


def example_audit() -> ClaimAudit:
    return ClaimAudit(
        audit_id="audit-1",
        claim="A test claim.",
        source=SourceMetadata(),
        candidates=[],
        deterministic_checks=DeterministicChecks(normalized_claim_sha256="a" * 64),
        proposal=Proposal(
            status=ProposalStatus.REVIEW_REQUIRED, reasons=["test"], policy_version="test"
        ),
        provenance=Provenance(
            application_version="test",
            retrieval_version="test",
            question_set_version="test",
            policy_version="test",
        ),
    )


def test_store_appends_create_and_review_events(tmp_path) -> None:
    store = AuditStore(tmp_path / "audits.db")
    store.save(example_audit())
    updated = store.add_review(
        "audit-1",
        HumanReview(
            decision=HumanDecision.ACCEPT,
            notes="Checked against the source.",
            reviewer="reviewer-1",
        ),
    )
    assert updated is not None
    assert updated.human_review is not None
    assert [event.event_type for event in store.events("audit-1")] == [
        "audit.created",
        "source.loaded",
        "document.parsed",
        "retrieval.started",
        "retrieval.completed",
        "evidence.selected",
        "checks.completed",
        "judgment.completed",
        "proposal.created",
        "feedback.recorded",
        "review.accepted",
    ]
