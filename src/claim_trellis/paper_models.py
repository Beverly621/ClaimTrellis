"""Paper Workflow contracts, separate from the frozen ClaimAudit judgment model."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from claim_trellis.document_blocks import validate_blocks
from claim_trellis.models import DocumentBlock, SourceAccessTier, utc_now

TextID = Annotated[str, Field(min_length=1, max_length=200)]
Marker = Annotated[str, Field(min_length=1, max_length=200)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateRequest(Contract):
    idempotency_key: str = Field(min_length=8, max_length=200)


class WorkflowRecord(Contract):
    project_id: TextID
    created_at: datetime = Field(default_factory=utc_now)


class ProjectCreate(CreateRequest):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class ResearchProject(Contract):
    project_id: TextID
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=utc_now)


class ManuscriptCreate(CreateRequest):
    filename: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=2_000_000)
    media_type: str = Field(default="text/plain", max_length=200)
    blocks: list[DocumentBlock] = Field(default_factory=list, max_length=100_000)
    parser_version: str = Field(default="supplied-normalized-text-v1", max_length=100)

    @model_validator(mode="after")
    def grounded(self) -> ManuscriptCreate:
        validate_blocks(self.text, self.blocks)
        return self


class Manuscript(WorkflowRecord):
    manuscript_id: TextID
    project_id: TextID
    filename: str
    media_type: str
    text: str
    content_sha256: str
    blocks: list[DocumentBlock]
    parser_version: str
    created_at: datetime = Field(default_factory=utc_now)


class ExactSpan(Contract):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self) -> ExactSpan:
        if self.end <= self.start:
            raise ValueError("An exact span must be nonempty and ordered.")
        return self


class CandidateCreate(CreateRequest):
    sentence_span: ExactSpan
    clause_span: ExactSpan
    citation_markers: list[Marker] = Field(min_length=1, max_length=50)


class ClaimCandidate(WorkflowRecord):
    candidate_id: TextID
    project_id: TextID
    manuscript_id: TextID
    source_sentence: str
    sentence_span: ExactSpan
    exact_span_start: int = Field(ge=0)
    exact_span_end: int = Field(gt=0)
    original_span: str
    citation_markers: list[Marker] = Field(min_length=1, max_length=50)
    suggested_clause_span: ExactSpan | None = None
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    confirmed_claim: str | None = Field(default=None, min_length=3, max_length=20_000)
    extraction_version: str
    sha256: str
    state_revision: int = Field(default=0, ge=0)
    extraction_warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def consistent(self) -> ClaimCandidate:
        if (
            not self.sentence_span.start
            <= self.exact_span_start
            < self.exact_span_end
            <= self.sentence_span.end
        ):
            raise ValueError("Candidate clause must lie within its original sentence.")
        if (self.status == "confirmed") != (self.confirmed_claim is not None):
            raise ValueError("Only a confirmed candidate has a human-confirmed claim.")
        return self


class ReferenceCreate(CreateRequest):
    span: ExactSpan
    markers: list[Marker] = Field(min_length=1, max_length=50)
    title: str | None = Field(default=None, max_length=2000)
    authors: list[str] = Field(default_factory=list, max_length=100)
    year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = Field(default=None, max_length=500)


class ClaimRubric(Contract):
    atomic: bool
    faithful: bool
    necessary_context: bool


class CandidateDecision(CreateRequest):
    decision: Literal["confirm", "edit", "reject"]
    expected_state_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1, max_length=200)
    notes: str = Field(min_length=1, max_length=4000)
    rubric: ClaimRubric | None = None
    confirmed_claim: str | None = Field(default=None, min_length=3, max_length=20_000)

    @model_validator(mode="after")
    def human_gate(self) -> CandidateDecision:
        if (self.decision == "edit") != (self.confirmed_claim is not None):
            raise ValueError("Only Edit supplies a distinct human-confirmed claim.")
        if self.confirmed_claim is not None and not self.confirmed_claim.strip():
            raise ValueError("A confirmed claim cannot be blank.")
        if self.decision != "reject" and (
            self.rubric is None or not all(self.rubric.model_dump().values())
        ):
            raise ValueError("Confirm/Edit require all three human rubric checks.")
        if not self.reviewer.strip() or not self.notes.strip():
            raise ValueError("Reviewer and notes cannot be blank.")
        return self


class ReferenceEntry(WorkflowRecord):
    reference_id: TextID
    project_id: TextID
    manuscript_id: TextID
    manuscript_locator: str
    span: ExactSpan
    markers: list[Marker] = Field(min_length=1, max_length=50)
    raw_reference: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    sha256: str
    parser_version: str = "manual-reference-v1"
    created_at: datetime = Field(default_factory=utc_now)


class SourceLinkCreate(CreateRequest):
    candidate_id: TextID
    reference_id: TextID
    source_document_id: TextID | None = None


class ClaimSourceLink(WorkflowRecord):
    link_id: TextID
    project_id: TextID
    candidate_id: TextID
    reference_id: TextID
    source_document_id: TextID | None = None
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    state_revision: int = Field(default=0, ge=0)
    suggestion_reasons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def confirmed_source(self) -> ClaimSourceLink:
        if self.status == "confirmed" and self.source_document_id is None:
            raise ValueError("Confirmed mapping requires an identified uploaded source.")
        return self


class PaperSourceMetadata(Contract):
    title: str | None = Field(default=None, max_length=2000)
    authors: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=100
    )
    journal: str | None = Field(default=None, max_length=1000)
    year: int | None = Field(default=None, ge=1900, le=2100)
    doi: str | None = Field(default=None, max_length=500)
    access_tier: SourceAccessTier = SourceAccessTier.UNKNOWN


class SourceDocument(WorkflowRecord):
    source_document_id: TextID
    filename: str
    media_type: str
    text: str
    document_hash: str
    metadata: PaperSourceMetadata
    blocks: list[DocumentBlock]
    parser_version: str
    parsing_warnings: list[str] = Field(default_factory=list)


class MappingDecision(CreateRequest):
    decision: Literal["confirm", "reject"]
    expected_state_revision: int = Field(ge=0)
    reviewer: str = Field(min_length=1, max_length=200)
    notes: str = Field(min_length=1, max_length=4000)
    source_document_id: TextID | None = None
    identity_confirmed: bool = False

    @model_validator(mode="after")
    def human_identity(self) -> MappingDecision:
        if self.decision == "confirm" and (
            not self.identity_confirmed or self.source_document_id is None
        ):
            raise ValueError(
                "Confirm requires a selected source and explicit human identity confirmation."
            )
        if self.decision == "reject" and (
            self.identity_confirmed or self.source_document_id is not None
        ):
            raise ValueError("Reject does not confirm source identity.")
        if not self.reviewer.strip() or not self.notes.strip():
            raise ValueError("Reviewer and notes cannot be blank.")
        return self


class MappingSuggestions(Contract):
    links: list[ClaimSourceLink]
    warnings: list[str]


class ProjectAuditLink(WorkflowRecord):
    audit_link_id: TextID
    project_id: TextID
    claim_source_link_id: TextID
    audit_id: TextID
    created_at: datetime = Field(default_factory=utc_now)


class WorkflowEvent(Contract):
    event_id: str
    project_id: str
    record_id: str | None = None
    event_type: str
    payload: dict[str, object]
    created_at: datetime = Field(default_factory=utc_now)


Record = (
    Manuscript
    | ClaimCandidate
    | ReferenceEntry
    | ClaimSourceLink
    | ProjectAuditLink
    | SourceDocument
)
RECORD_MODELS: dict[str, type[WorkflowRecord]] = {
    "manuscript": Manuscript,
    "candidate": ClaimCandidate,
    "reference": ReferenceEntry,
    "source_link": ClaimSourceLink,
    "audit_link": ProjectAuditLink,
    "source_document": SourceDocument,
}
ID_FIELDS = {
    "manuscript": "manuscript_id",
    "candidate": "candidate_id",
    "reference": "reference_id",
    "source_link": "link_id",
    "audit_link": "audit_link_id",
    "source_document": "source_document_id",
}
