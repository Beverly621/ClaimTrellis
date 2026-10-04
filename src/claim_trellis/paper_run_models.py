"""Orchestration state only: ClaimAudit remains the sole judgment model."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from claim_trellis.models import ClaimAudit, utc_now
from claim_trellis.paper_models import Contract, CreateRequest, TextID

RunStatus = Literal["pending", "running", "completed", "failed", "quota_blocked"]


class AuditInputSnapshot(Contract):
    candidate_id: TextID
    candidate_sha256: str
    candidate_state_revision: int
    confirmed_claim: str
    reference_id: TextID
    reference_sha256: str
    source_link_id: TextID
    source_link_state_revision: int
    source_document_id: TextID
    source_document_hash: str
    source_metadata_hash: str
    source_blocks_hash: str
    parser_version: str
    identity_event_id: str


class AuditRunCreate(CreateRequest):
    source_link_ids: list[TextID] = Field(min_length=1, max_length=200)
    use_judgment_provider: bool = True

    @model_validator(mode="after")
    def unique_links(self) -> AuditRunCreate:
        if len(set(self.source_link_ids)) != len(self.source_link_ids):
            raise ValueError("Selected source links must be unique.")
        self.source_link_ids = sorted(self.source_link_ids)
        return self


class AuditItemExecute(CreateRequest):
    input_snapshot_hash: str = Field(min_length=64, max_length=64)


class ProjectAuditRunItem(Contract):
    item_id: str
    run_id: str
    project_id: str
    claim_source_link_id: str
    snapshot: AuditInputSnapshot
    input_snapshot_hash: str
    use_judgment_provider: bool
    status: RunStatus = "pending"
    audit_id: str | None = None
    error_code: str | None = None
    attempts: int = 0
    retry_allowed: bool = True
    updated_at: datetime = Field(default_factory=utc_now)


class PaperQuotaPreflight(Contract):
    requested_links: int
    provider_calls_available: int | None
    runnable_now: int
    blocked: int
    reason: str | None = None
    estimate_only: bool = True


class ProjectAuditRun(Contract):
    run_id: str
    project_id: str
    requested_by: str
    status: RunStatus = "pending"
    created_at: datetime = Field(default_factory=utc_now)
    quota: PaperQuotaPreflight
    items: list[ProjectAuditRunItem]


class ExecutionClaim(Contract):
    item: ProjectAuditRunItem
    lease_token: str | None = None
    checkpoint: ClaimAudit | None = None
