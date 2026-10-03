from __future__ import annotations

from claim_trellis.models import (
    DeterministicChecks,
    JudgmentResult,
    Proposal,
    ProposalStatus,
    SourceAccessTier,
)

POLICY_VERSION = "fail-closed-v2"


def _aligned(choice: str, allowed: set[str]) -> bool:
    return choice in allowed


def propose_disposition(
    checks: DeterministicChecks,
    judgment: JudgmentResult | None,
    *,
    source_access_tier: SourceAccessTier,
    relation_confidence_threshold: float = 0.90,
    alignment_confidence_threshold: float = 0.85,
    service_errors: list[str] | None = None,
) -> Proposal:
    errors = service_errors or []
    if checks.selected_evidence_sha256 is None:
        return Proposal(
            status=ProposalStatus.EVIDENCE_MISSING,
            reasons=["No evidence passage was retrieved."],
            policy_version=POLICY_VERSION,
        )
    if checks.quote_requested and checks.quote_found is False:
        return Proposal(
            status=ProposalStatus.EVIDENCE_MISSING,
            reasons=["The requested quote was not found in the supplied source."],
            policy_version=POLICY_VERSION,
        )
    if errors:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=["A service failure prevented a complete semantic evaluation.", *errors],
            policy_version=POLICY_VERSION,
        )
    if judgment is None:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "No structured judgment provider was run; deterministic checks alone cannot establish semantic support."
            ],
            policy_version=POLICY_VERSION,
        )
    if judgment.prompt_injection.noul >= 0.5:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "The evidence may contain instructions intended to manipulate an AI evaluator."
            ],
            policy_version=POLICY_VERSION,
        )
    if judgment.context_sufficiency.noul < 0.70:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "The provider judged the selected passage insufficient for a reliable comparison."
            ],
            policy_version=POLICY_VERSION,
        )
    relation = judgment.relation
    if relation.confidence < relation_confidence_threshold:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                f"Relation confidence {relation.confidence:.2f} is below the experimental threshold."
            ],
            policy_version=POLICY_VERSION,
        )
    if relation.choice == "contradicts":
        return Proposal(
            status=ProposalStatus.CONTRADICTED,
            reasons=["The selected evidence was judged to contradict the claim."],
            policy_version=POLICY_VERSION,
        )
    if relation.choice == "partially_supports":
        return Proposal(
            status=ProposalStatus.PARTIALLY_SUPPORTED,
            reasons=["The selected evidence supports only part of the claim."],
            policy_version=POLICY_VERSION,
        )
    if relation.choice == "not_addressed":
        if source_access_tier != SourceAccessTier.FULL_TEXT:
            return Proposal(
                status=ProposalStatus.REVIEW_REQUIRED,
                reasons=[
                    "The available evidence is not full text, so silence cannot establish that the source is unsupported."
                ],
                policy_version=POLICY_VERSION,
            )
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "The selected evidence does not address the claim; Top-K retrieval is not exhaustive proof of full-source silence."
            ],
            policy_version=POLICY_VERSION,
        )
    if relation.choice == "source_unavailable":
        return Proposal(
            status=ProposalStatus.EVIDENCE_MISSING,
            reasons=["The source required for semantic comparison was unavailable."],
            policy_version=POLICY_VERSION,
        )
    if relation.choice == "insufficient_context":
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "The available context was insufficient for a reliable relationship judgment."
            ],
            policy_version=POLICY_VERSION,
        )
    if relation.choice != "supports":
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=["The semantic relation remained indeterminate."],
            policy_version=POLICY_VERSION,
        )
    if checks.unmatched_claim_numbers:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED,
            reasons=[
                "The semantic relation supports the claim, but at least one claim number was not found in the selected passage."
            ],
            policy_version=POLICY_VERSION,
        )

    blocking = [finding.reason for finding in checks.findings if finding.blocking]
    if blocking:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED, reasons=blocking, policy_version=POLICY_VERSION
        )

    alignments = [
        (judgment.scope_alignment, {"aligned", "claim_narrower"}, "scope"),
        (judgment.population_alignment, {"aligned", "not_applicable"}, "population"),
        (judgment.causal_fidelity, {"faithful", "not_applicable"}, "causal framing"),
    ]
    for field, name in (
        ("intervention_or_exposure_alignment", "intervention or exposure"),
        ("comparator_alignment", "comparator"),
        ("outcome_alignment", "outcome"),
        ("timeframe_alignment", "timeframe"),
        ("direction_alignment", "direction"),
    ):
        dimension = getattr(judgment, field)
        if dimension is None:
            if judgment.question_set_version.endswith("v3"):
                return Proposal(
                    status=ProposalStatus.REVIEW_REQUIRED,
                    reasons=[f"Required {name} judgment is missing."],
                    policy_version=POLICY_VERSION,
                )
            continue  # Legacy snapshots/providers remain readable.
        alignments.append((dimension, {"aligned", "not_applicable"}, name))
    reasons: list[str] = []
    uncertainty = False
    for alignment, allowed, name in alignments:
        if alignment.confidence < alignment_confidence_threshold:
            uncertainty = True
            reasons.append(f"{name.capitalize()} confidence is below the experimental threshold.")
        elif not _aligned(alignment.choice, allowed):
            uncertainty = uncertainty or alignment.choice == "unclear"
            reasons.append(f"The {name} judgment is {alignment.choice}.")
    if reasons:
        return Proposal(
            status=ProposalStatus.REVIEW_REQUIRED
            if uncertainty
            else ProposalStatus.PARTIALLY_SUPPORTED,
            reasons=reasons,
            policy_version=POLICY_VERSION,
        )
    return Proposal(
        status=ProposalStatus.SUPPORTED,
        reasons=[
            "All available structured dimensions and deterministic checks align; human confirmation is required."
        ],
        requires_human_review=True,
        auto_accepted=False,
        policy_version=POLICY_VERSION,
    )
