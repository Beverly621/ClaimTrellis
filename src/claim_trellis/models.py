from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceAccessTier(StrEnum):
    FULL_TEXT = "full_text"
    ABSTRACT = "abstract"
    EXCERPT = "excerpt"
    UNKNOWN = "unknown"


class RelationLabel(StrEnum):
    SUPPORTS = "supports"
    PARTIALLY_SUPPORTS = "partially_supports"
    CONTRADICTS = "contradicts"
    NOT_ADDRESSED = "not_addressed"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    SOURCE_UNAVAILABLE = "source_unavailable"


class ProposalStatus(StrEnum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    UNSUPPORTED = "unsupported"
    EVIDENCE_MISSING = "evidence_missing"
    REVIEW_REQUIRED = "review_required"


class HumanDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVISE = "revise"
    DEFER = "defer"


class ReviewStatus(StrEnum):
    PENDING = "pending_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DEFERRED = "deferred"
    REQUESTED = "revision_requested"
    RUNNING = "revision_running"
    FAILED = "revision_failed"
    SUPERSEDED = "superseded"


class RevisionStatus(StrEnum):
    REQUESTED = "revision_requested"
    RUNNING = "revision_running"
    FAILED = "revision_failed"
    COMPLETED = "revision_completed"


class SourceMetadata(BaseModel):
    title: str | None = None
    journal: str | None = None
    year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = None
    pmid: str | None = None
    url: HttpUrl | None = None
    access_tier: SourceAccessTier = SourceAccessTier.UNKNOWN
    content_sha256: str | None = None


class EvidencePassage(BaseModel):
    passage_id: str
    text: str
    locator: str
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)
    sha256: str
    block_ids: list[str] = Field(default_factory=list)
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None


class DocumentBlockReference(BaseModel):
    """Persist locators and hashes, not the full normalized source text."""

    block_id: str
    block_type: str
    locator: str
    page: int | None = None
    section: str | None = None
    paragraph: int | None = None
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=0)
    sha256: str


class DocumentBlock(DocumentBlockReference):
    text: str


class EvidenceSet(BaseModel):
    passages: list[EvidencePassage] = Field(min_length=1, max_length=3)
    sha256: str


class CheckFinding(BaseModel):
    check_id: str
    status: str
    reason: str
    blocking: bool = False


class RetrievedCandidate(BaseModel):
    passage: EvidencePassage
    score: float
    rank: int = Field(ge=1)


class NumericToken(BaseModel):
    raw: str
    normalized: float
    unit: str | None = None


class DeterministicChecks(BaseModel):
    normalized_claim_sha256: str
    selected_evidence_sha256: str | None = None
    quote_requested: bool = False
    quote_found: bool | None = None
    claim_numbers: list[NumericToken] = Field(default_factory=list)
    evidence_numbers: list[NumericToken] = Field(default_factory=list)
    unmatched_claim_numbers: list[NumericToken] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    check_set_version: str = "deterministic-v1"
    findings: list[CheckFinding] = Field(default_factory=list)


class ChoiceJudgment(BaseModel):
    choice: str
    probabilities: dict[str, float]
    confidence: float = Field(ge=0, le=1)

    @field_validator("probabilities")
    @classmethod
    def validate_probabilities(cls, value: dict[str, float]) -> dict[str, float]:
        if not value:
            raise ValueError("probabilities must not be empty")
        if any(
            not math.isfinite(probability) or probability < 0 or probability > 1
            for probability in value.values()
        ):
            raise ValueError("probabilities must be between 0 and 1")
        if abs(sum(value.values()) - 1.0) > 0.03:
            raise ValueError("probabilities must sum to approximately 1")
        return value


class NoulJudgment(BaseModel):
    noul: float = Field(ge=0, le=1)


class JudgmentResult(BaseModel):
    provider: str
    requested_model: str
    resolved_model: str
    question_set_version: str
    relation: ChoiceJudgment
    scope_alignment: ChoiceJudgment
    population_alignment: ChoiceJudgment
    causal_fidelity: ChoiceJudgment
    context_sufficiency: NoulJudgment
    prompt_injection: NoulJudgment
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    retry_count: int = Field(ge=0)
    raw_answers: dict[str, Any]
    judgment_summary: str | None = Field(default=None, max_length=2000)
    claim_type: ChoiceJudgment | None = None
    intervention_or_exposure_alignment: ChoiceJudgment | None = None
    comparator_alignment: ChoiceJudgment | None = None
    outcome_alignment: ChoiceJudgment | None = None
    timeframe_alignment: ChoiceJudgment | None = None
    direction_alignment: ChoiceJudgment | None = None

    @field_validator("relation")
    @classmethod
    def validate_relation_label(cls, value: ChoiceJudgment) -> ChoiceJudgment:
        RelationLabel(value.choice)
        return value


class Proposal(BaseModel):
    status: ProposalStatus
    reasons: list[str]
    requires_human_review: bool = True
    auto_accepted: bool = False
    policy_version: str


class HumanReview(BaseModel):
    decision: HumanDecision
    notes: str = Field(min_length=1, max_length=10_000)
    reviewer: str = Field(min_length=1, max_length=200)
    created_at: datetime = Field(default_factory=utc_now)
    proposal_id: str | None = None
    proposal_version: int | None = None


class Provenance(BaseModel):
    application_version: str
    retrieval_version: str
    judgment_provider: str | None = None
    question_set_version: str
    policy_version: str
    created_at: datetime = Field(default_factory=utc_now)
    parser_version: str = "legacy-flat-v1"
    check_set_version: str = "deterministic-v1"
    requested_model: str | None = None
    resolved_model: str | None = None
    evidence_set_hash: str | None = None


class ClaimAudit(BaseModel):
    audit_id: str
    claim: str
    citation: str | None = None
    source: SourceMetadata
    candidates: list[RetrievedCandidate]
    selected_passage: EvidencePassage | None = None
    deterministic_checks: DeterministicChecks
    judgment_result: JudgmentResult | None = None
    proposal: Proposal
    human_review: HumanReview | None = None
    provenance: Provenance
    service_errors: list[str] = Field(default_factory=list)
    current_proposal_id: str | None = None
    current_proposal_version: int = 1
    review_status: ReviewStatus = ReviewStatus.PENDING
    state_revision: int = 0
    source_blocks: list[DocumentBlockReference] = Field(default_factory=list)
    evidence_set: EvidenceSet | None = None
    requested_quote: str | None = None


class ProposalVersion(BaseModel):
    """Immutable judgment snapshot; review_status is a separately stored projection."""

    model_config = ConfigDict(frozen=True)
    audit_id: str
    proposal_id: str
    version: int
    parent_proposal_id: str | None = None
    relation: RelationLabel | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    policy: Proposal
    judgment: JudgmentResult | None = None
    created_at: datetime = Field(default_factory=utc_now)
    review_status: ReviewStatus = ReviewStatus.PENDING
    evidence_set: EvidenceSet | None = None
    deterministic_checks: DeterministicChecks | None = None
    provenance: Provenance | None = None


class RevisionContext(BaseModel):
    previous_proposal: ProposalVersion
    deterministic_checks: DeterministicChecks
    source_completeness: SourceAccessTier
    human_feedback: str
    revision_number: int


class RevisionRequest(BaseModel):
    proposal_id: str = Field(min_length=1, max_length=100)
    proposal_version: int = Field(ge=1)
    expected_state_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=100)
    reviewer: str = Field(min_length=1, max_length=200)
    feedback: str = Field(min_length=1, max_length=10000)
    selected_passage_ids: list[str] | None = Field(default=None, min_length=1, max_length=3)

    @field_validator("selected_passage_ids")
    @classmethod
    def unique_passages(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("Evidence passage IDs must be unique.")
        return value

    @field_validator("reviewer", "feedback")
    @classmethod
    def require_nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Must not be blank.")
        return value


class RevisionRun(BaseModel):
    revision_id: str
    audit_id: str
    request: RevisionRequest
    status: RevisionStatus
    created_at: datetime
    updated_at: datetime
    result_proposal_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class AuditRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=20_000)
    source_text: str = Field(min_length=1, max_length=2_000_000)
    citation: str | None = Field(default=None, max_length=2_000)
    quote: str | None = Field(default=None, max_length=20_000)
    source: SourceMetadata = Field(default_factory=SourceMetadata)
    top_k: int = Field(default=10, ge=1, le=20)
    use_judgment_provider: bool = True
    source_blocks: list[DocumentBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_blocks(self) -> AuditRequest:
        import hashlib

        from claim_trellis.document_blocks import validate_blocks

        validate_blocks(self.source_text, self.source_blocks)
        if (
            self.source.content_sha256 is not None
            and self.source.content_sha256 != hashlib.sha256(self.source_text.encode()).hexdigest()
        ):
            raise ValueError("Source content hash must match the supplied normalized text.")
        return self


class EvidenceSearchRequest(BaseModel):
    claim: str = Field(min_length=3, max_length=20_000)
    source_text: str = Field(min_length=1, max_length=2_000_000)
    top_k: int = Field(default=10, ge=1, le=20)
    source_blocks: list[DocumentBlock] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_source_blocks(self) -> EvidenceSearchRequest:
        from claim_trellis.document_blocks import validate_blocks

        validate_blocks(self.source_text, self.source_blocks)
        return self


class HumanReviewRequest(BaseModel):
    decision: HumanDecision
    notes: str = Field(min_length=1, max_length=10_000)
    reviewer: str = Field(min_length=1, max_length=200)
    proposal_id: str | None = None
    proposal_version: int | None = Field(default=None, ge=1)
    expected_state_revision: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_reference(self) -> HumanReviewRequest:
        refs = (self.proposal_id, self.proposal_version, self.expected_state_revision)
        if any(item is not None for item in refs) and not all(item is not None for item in refs):
            raise ValueError(
                "Supply proposal_id, proposal_version and expected_state_revision together."
            )
        if not self.notes.strip() or not self.reviewer.strip():
            raise ValueError("Reviewer and notes must not be blank.")
        return self


class AuditEvent(BaseModel):
    event_id: str
    audit_id: str
    event_type: str
    created_at: datetime
    payload: dict[str, Any]
    proposal_id: str | None = None
    proposal_version: int | None = None


class ParsedCitationSentence(BaseModel):
    sentence: str
    markers: list[str]
    start_char: int = Field(ge=0)
    end_char: int = Field(ge=0)


class ParsedDocument(BaseModel):
    filename: str
    media_type: str
    text: str
    content_sha256: str
    character_count: int = Field(ge=0)
    citation_sentences: list[ParsedCitationSentence]
    warnings: list[str] = Field(default_factory=list)
    blocks: list[DocumentBlock] = Field(default_factory=list)
    parser_version: str = "legacy-flat-v1"
