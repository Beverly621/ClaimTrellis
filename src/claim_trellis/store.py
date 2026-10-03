"""Ownership-aware asynchronous storage contract and local SQLite adapter."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from anyio import to_thread

from claim_trellis.models import (
    AuditEvent,
    ClaimAudit,
    HumanReviewRequest,
    JudgmentResult,
    Proposal,
    ProposalVersion,
    RevisionRequest,
    RevisionRun,
)
from claim_trellis.storage import AuditStore

LOCAL_USER_ID = "local-workspace"


class AuditStoreProtocol(Protocol):
    async def save(self, owner_user_id: str, audit: ClaimAudit) -> ClaimAudit: ...

    async def get(self, owner_user_id: str, audit_id: str) -> ClaimAudit | None: ...

    async def list_audits(
        self, owner_user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ClaimAudit]: ...

    async def proposals(self, owner_user_id: str, audit_id: str) -> list[ProposalVersion]: ...

    async def review(
        self, owner_user_id: str, audit_id: str, request: HumanReviewRequest
    ) -> ClaimAudit: ...

    async def request_revision(
        self, owner_user_id: str, audit_id: str, request: RevisionRequest
    ) -> tuple[RevisionRun, bool]: ...

    async def start_revision(self, owner_user_id: str, run: RevisionRun) -> None: ...

    async def finish_revision(
        self,
        owner_user_id: str,
        run: RevisionRun,
        judgment: JudgmentResult | None,
        policy: Proposal,
    ) -> RevisionRun: ...

    async def fail_revision(
        self, owner_user_id: str, run: RevisionRun, code: str, message: str
    ) -> RevisionRun: ...

    async def revisions(self, owner_user_id: str, audit_id: str) -> list[RevisionRun]: ...

    async def events(self, owner_user_id: str, audit_id: str) -> list[AuditEvent]: ...


class SQLiteAsyncStore:
    """Threadpool adapter for the existing single-user SQLite lifecycle code."""

    def __init__(self, path: Path | None = None, *, legacy_store: AuditStore | None = None) -> None:
        if legacy_store is None and path is None:
            raise ValueError("SQLiteAsyncStore needs a path or existing store.")
        if legacy_store is not None:
            self.legacy_store = legacy_store
        else:
            assert path is not None
            self.legacy_store = AuditStore(path)

    @staticmethod
    def _owner(owner_user_id: str) -> None:
        if owner_user_id != LOCAL_USER_ID:
            raise KeyError("Audit not found.")

    async def save(self, owner_user_id: str, audit: ClaimAudit) -> ClaimAudit:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.save, audit)

    async def get(self, owner_user_id: str, audit_id: str) -> ClaimAudit | None:
        if owner_user_id != LOCAL_USER_ID:
            return None
        return await to_thread.run_sync(self.legacy_store.get, audit_id)

    async def list_audits(
        self, owner_user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ClaimAudit]:
        self._owner(owner_user_id)
        return await to_thread.run_sync(
            lambda: self.legacy_store.list_audits(limit=limit, offset=offset)
        )

    async def proposals(self, owner_user_id: str, audit_id: str) -> list[ProposalVersion]:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.proposals, audit_id)

    async def review(
        self, owner_user_id: str, audit_id: str, request: HumanReviewRequest
    ) -> ClaimAudit:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.review, audit_id, request)

    async def request_revision(
        self, owner_user_id: str, audit_id: str, request: RevisionRequest
    ) -> tuple[RevisionRun, bool]:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.request_revision, audit_id, request)

    async def start_revision(self, owner_user_id: str, run: RevisionRun) -> None:
        self._owner(owner_user_id)
        await to_thread.run_sync(self.legacy_store.start_revision, run)

    async def finish_revision(
        self,
        owner_user_id: str,
        run: RevisionRun,
        judgment: JudgmentResult | None,
        policy: Proposal,
    ) -> RevisionRun:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.finish_revision, run, judgment, policy)

    async def fail_revision(
        self, owner_user_id: str, run: RevisionRun, code: str, message: str
    ) -> RevisionRun:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.fail_revision, run, code, message)

    async def revisions(self, owner_user_id: str, audit_id: str) -> list[RevisionRun]:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.revisions, audit_id)

    async def events(self, owner_user_id: str, audit_id: str) -> list[AuditEvent]:
        self._owner(owner_user_id)
        return await to_thread.run_sync(self.legacy_store.events, audit_id)
