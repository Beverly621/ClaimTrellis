"""Owner-scoped, fenced one-item orchestration of the existing P0 audit pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import uuid4

from anyio import to_thread

from claim_trellis.audit import run_audit
from claim_trellis.config import Settings
from claim_trellis.hosted_usage import HostedUsageLimit, PostgresUsageGuard
from claim_trellis.models import (
    AuditRequest,
    ClaimAudit,
    JudgmentResult,
    RevisionContext,
    SourceMetadata,
    utc_now,
)
from claim_trellis.paper_models import (
    ClaimCandidate,
    ClaimSourceLink,
    ProjectAuditLink,
    ReferenceEntry,
    SourceDocument,
)
from claim_trellis.paper_run_models import (
    AuditInputSnapshot,
    AuditItemExecute,
    AuditRunCreate,
    ExecutionClaim,
    PaperQuotaPreflight,
    ProjectAuditRun,
    ProjectAuditRunItem,
)
from claim_trellis.paper_store import (
    PaperWorkflowStore,
    WorkflowNotFound,
    _Connection,
    digest,
    stable_id,
)
from claim_trellis.postgres_store import PostgresAuditStore
from claim_trellis.provider import JudgmentProvider, ProviderError
from claim_trellis.storage import LifecycleConflict
from claim_trellis.store import SQLiteAsyncStore


def unpack(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


class PaperBudgetBlocked(Exception):
    pass


class PaperRunStore:
    MAX_ATTEMPTS = 3

    def __init__(
        self,
        workflow: PaperWorkflowStore,
        audits: SQLiteAsyncStore | PostgresAuditStore,
        settings: Settings,
    ) -> None:
        self.workflow, self.audits, self.settings = workflow, audits, settings
        self.lease_seconds = max(
            180, int(settings.jev_timeout_seconds * (settings.jev_max_retries + 1)) + 60
        )
        if workflow.path is not None:
            with sqlite3.connect(workflow.path) as conn:
                conn.executescript("""
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS paper_audit_runs (
                  run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                  creation_sha256 TEXT NOT NULL, record_json TEXT NOT NULL, created_at TEXT NOT NULL,
                  UNIQUE(run_id,project_id,owner_user_id), FOREIGN KEY(project_id,owner_user_id) REFERENCES research_projects(project_id,owner_user_id));
                CREATE TABLE IF NOT EXISTS paper_audit_items (
                  item_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                  source_link_id TEXT NOT NULL, record_json TEXT NOT NULL, checkpoint_json TEXT,
                  lease_token TEXT, lease_until TEXT, requests_json TEXT NOT NULL,
                  UNIQUE(item_id,project_id,owner_user_id), UNIQUE(project_id,owner_user_id,source_link_id),
                  FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id),
                  FOREIGN KEY(source_link_id,project_id,owner_user_id) REFERENCES paper_workflow_records(record_id,project_id,owner_user_id));
                CREATE TABLE IF NOT EXISTS paper_run_members (
                  run_id TEXT NOT NULL, item_id TEXT NOT NULL, project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL,
                  PRIMARY KEY(run_id,item_id),
                  FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id),
                  FOREIGN KEY(item_id,project_id,owner_user_id) REFERENCES paper_audit_items(item_id,project_id,owner_user_id));
                CREATE TABLE IF NOT EXISTS paper_provider_usage (
                  usage_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, run_id TEXT NOT NULL, project_id TEXT NOT NULL,
                  owner_user_id TEXT NOT NULL, lease_token TEXT NOT NULL, status TEXT NOT NULL,
                  result_json TEXT, error_code TEXT, created_at TEXT NOT NULL, completed_at TEXT,
                  CHECK(status IN ('started','succeeded','failed','unknown')),
                  FOREIGN KEY(item_id,project_id,owner_user_id) REFERENCES paper_audit_items(item_id,project_id,owner_user_id),
                  FOREIGN KEY(run_id,project_id,owner_user_id) REFERENCES paper_audit_runs(run_id,project_id,owner_user_id));
                CREATE INDEX IF NOT EXISTS idx_paper_usage_owner ON paper_provider_usage(owner_user_id,created_at);
                CREATE INDEX IF NOT EXISTS idx_paper_usage_item ON paper_provider_usage(item_id,created_at);
                """)

    async def inputs(
        self, conn: _Connection, owner: str, project: str, link_id: str
    ) -> tuple[AuditInputSnapshot, AuditRequest]:
        get = self.workflow._record
        link = cast(ClaimSourceLink, await get(conn, owner, project, link_id, "source_link"))
        claim = cast(
            ClaimCandidate, await get(conn, owner, project, link.candidate_id, "candidate")
        )
        ref = cast(ReferenceEntry, await get(conn, owner, project, link.reference_id, "reference"))
        if (
            claim.status != "confirmed"
            or not claim.confirmed_claim
            or not claim.confirmed_claim.strip()
            or link.status != "confirmed"
            or not link.source_document_id
        ):
            raise LifecycleConflict(
                "Only human-confirmed claims and source identities may be audited."
            )
        if ref.manuscript_id != claim.manuscript_id:
            raise LifecycleConflict("Claim and reference must belong to the same manuscript.")
        source = cast(
            SourceDocument,
            await get(conn, owner, project, link.source_document_id, "source_document"),
        )
        if (
            hashlib.sha256(claim.original_span.encode()).hexdigest() != claim.sha256
            or hashlib.sha256(ref.raw_reference.encode()).hexdigest() != ref.sha256
        ):
            raise LifecycleConflict("Claim or reference no longer matches its original text hash.")
        if hashlib.sha256(source.text.encode()).hexdigest() != source.document_hash:
            raise LifecycleConflict("Source hash does not match the stored document.")
        events = await conn.execute(
            "SELECT event_id,payload_json FROM paper_workflow_events WHERE owner_user_id=? AND project_id=? AND record_id=? AND event_type='source_link.confirmed' ORDER BY event_seq DESC",
            (owner, project, link_id),
        )
        event_id = None
        for event in events:
            p = unpack(event["payload_json"])
            if (
                p.get("request", {}).get("identity_confirmed") is True
                and p.get("source_document_id") == source.source_document_id
                and p.get("source_document_hash") == source.document_hash
                and p.get("reference_sha256") == ref.sha256
                and p.get("candidate_sha256") == claim.sha256
                and p.get("candidate_state_revision") == claim.state_revision
                and p.get("state_revision") == link.state_revision
            ):
                event_id = event["event_id"]
                break
        if event_id is None:
            raise LifecycleConflict("An explicit human source-identity decision is required.")
        snapshot = AuditInputSnapshot(
            candidate_id=claim.candidate_id,
            candidate_sha256=claim.sha256,
            candidate_state_revision=claim.state_revision,
            confirmed_claim=claim.confirmed_claim,
            reference_id=ref.reference_id,
            reference_sha256=ref.sha256,
            source_link_id=link_id,
            source_link_state_revision=link.state_revision,
            source_document_id=source.source_document_id,
            source_document_hash=source.document_hash,
            source_metadata_hash=digest(source.metadata.model_dump(mode="json")),
            source_blocks_hash=digest([b.model_dump(mode="json") for b in source.blocks]),
            parser_version=source.parser_version,
            identity_event_id=event_id,
        )
        request = AuditRequest(
            claim=claim.confirmed_claim,
            source_text=source.text,
            source_blocks=source.blocks,
            citation=ref.raw_reference[:2000],
            source=SourceMetadata(
                **source.metadata.model_dump(exclude={"authors"}),
                content_sha256=source.document_hash,
            ),
        )
        return snapshot, request

    async def _budget(
        self, conn: _Connection, owner: str, run: str, *, ip_hash: str | None = None
    ) -> tuple[int, str | None]:
        s = self.settings
        if (
            s.paper_daily_user_limit is None
            or s.paper_run_provider_limit is None
            or s.paper_max_concurrent_provider_calls is None
        ):
            return 0, "paper_budget_unconfigured"
        since = (utc_now() - timedelta(hours=24)).isoformat()
        # Reservations, including failed/unknown calls, consume budget; never refund blindly.
        daily = (
            await conn.execute(
                "SELECT count(*) AS n FROM paper_provider_usage WHERE owner_user_id=? AND created_at>=?",
                (owner, since),
            )
        )[0]["n"]
        per_run = (
            await conn.execute(
                "SELECT count(*) AS n FROM paper_provider_usage WHERE run_id=? AND owner_user_id=?",
                (run, owner),
            )
        )[0]["n"]
        concurrent = (
            await conn.execute(
                "SELECT count(*) AS n FROM paper_provider_usage WHERE status='started'"
            )
        )[0]["n"]
        limits = [
            (s.paper_daily_user_limit - daily, "paper_daily_limit"),
            (s.paper_run_provider_limit - per_run, "paper_run_limit"),
            (s.paper_max_concurrent_provider_calls - concurrent, "paper_concurrency_limit"),
        ]
        if conn.postgres and s.auth_mode == "supabase":
            hosted = (
                await conn.execute(
                    "SELECT count(*) AS n FROM provider_usage WHERE owner_user_id=? AND created_at>=?",
                    (owner, since),
                )
            )[0]["n"]
            limits.append((s.paper_daily_user_limit - hosted, "hosted_user_limit"))
            if ip_hash:
                used = (
                    await conn.execute(
                        "SELECT count(*) AS n FROM provider_usage WHERE ip_hash=? AND created_at>=?",
                        (ip_hash, since),
                    )
                )[0]["n"]
                limits.append((PostgresUsageGuard.IP_LIMIT - used, "hosted_ip_limit"))
        available, reason = min(limits)
        return max(0, available), reason if available <= 0 else None

    async def _row(
        self, conn: _Connection, owner: str, project: str, run: str, item: str
    ) -> dict[str, Any]:
        rows = await conn.execute(
            "SELECT i.* FROM paper_audit_items i JOIN paper_run_members m ON m.item_id=i.item_id WHERE m.run_id=? AND i.item_id=? AND i.project_id=? AND i.owner_user_id=? AND m.owner_user_id=? AND m.project_id=?",
            (run, item, project, owner, owner, project),
        )
        if not rows:
            raise WorkflowNotFound("Run item not found.")
        return rows[0]

    async def _put(self, conn: _Connection, owner: str, item: ProjectAuditRunItem) -> None:
        item.updated_at = utc_now()
        await conn.execute(
            "UPDATE paper_audit_items SET record_json=? WHERE item_id=? AND owner_user_id=?",
            (item.model_dump(mode="json"), item.item_id, owner),
        )

    async def _recover(
        self, conn: _Connection, owner: str, row: dict[str, Any]
    ) -> ProjectAuditRunItem:
        item = ProjectAuditRunItem.model_validate(unpack(row["record_json"]))
        if (
            item.status == "running"
            and row["lease_until"]
            and (
                datetime.fromisoformat(row["lease_until"])
                if isinstance(row["lease_until"], str)
                else row["lease_until"]
            )
            < utc_now()
        ):
            usage = await conn.execute(
                "SELECT status FROM paper_provider_usage WHERE item_id=? AND owner_user_id=? AND status IN ('started','unknown')",
                (item.item_id, owner),
            )
            item.status, item.error_code = (
                "failed",
                "provider_outcome_unknown" if usage else "execution_interrupted",
            )
            item.retry_allowed = not bool(usage)
            await conn.execute(
                "UPDATE paper_provider_usage SET status='unknown' WHERE item_id=? AND owner_user_id=? AND status='started'",
                (item.item_id, owner),
            )
            await self._put(conn, owner, item)
            await self.workflow._event(
                conn,
                owner,
                item.project_id,
                "audit_item.interrupted",
                {"error_code": item.error_code},
                item.item_id,
            )
        return item

    async def _read(
        self, conn: _Connection, owner: str, project: str, run: str, *, ip_hash: str | None = None
    ) -> ProjectAuditRun:
        rows = await conn.execute(
            "SELECT record_json FROM paper_audit_runs WHERE run_id=? AND project_id=? AND owner_user_id=?",
            (run, project, owner),
        )
        if not rows:
            raise WorkflowNotFound("Audit run not found.")
        result = ProjectAuditRun.model_validate(unpack(rows[0]["record_json"]))
        members = await conn.execute(
            "SELECT i.* FROM paper_audit_items i JOIN paper_run_members m ON m.item_id=i.item_id WHERE m.run_id=? AND m.project_id=? AND m.owner_user_id=? ORDER BY i.item_id",
            (run, project, owner),
        )
        result.items = [await self._recover(conn, owner, row) for row in members]
        states = {i.status for i in result.items}
        result.status = (
            "completed"
            if states == {"completed"}
            else "running"
            if "running" in states
            else "pending"
            if "pending" in states
            else "failed"
            if "failed" in states
            else "quota_blocked"
        )
        available, reason = await self._budget(conn, owner, run, ip_hash=ip_hash)
        remaining = [i for i in result.items if i.status != "completed"]
        free = sum(not i.use_judgment_provider for i in remaining)
        runnable = min(len(remaining), available + free)
        result.quota = PaperQuotaPreflight(
            requested_links=len(result.items),
            provider_calls_available=available,
            runnable_now=runnable,
            blocked=len(remaining) - runnable,
            reason=reason if len(remaining) > runnable else None,
        )
        return result

    async def get(
        self, owner: str, project: str, run: str, *, ip_hash: str | None = None
    ) -> ProjectAuditRun:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, project)
            return await self._read(conn, owner, project, run, ip_hash=ip_hash)

    async def list(
        self, owner: str, project: str, limit: int = 50, offset: int = 0
    ) -> list[ProjectAuditRun]:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, project)
            rows = await conn.execute(
                "SELECT run_id FROM paper_audit_runs WHERE owner_user_id=? AND project_id=? ORDER BY created_at DESC,run_id LIMIT ? OFFSET ?",
                (owner, project, limit, offset),
            )
            return [await self._read(conn, owner, project, row["run_id"]) for row in rows]

    async def plan(
        self, owner: str, project: str, request: AuditRunCreate, *, ip_hash: str | None = None
    ) -> ProjectAuditRun:
        run_id = stable_id(project, "run:" + request.idempotency_key)
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, project)
            snapshots = [
                await self.inputs(conn, owner, project, link) for link in request.source_link_ids
            ]
            fingerprint = digest(
                {
                    "request": request.model_dump(mode="json"),
                    "inputs": [s.model_dump(mode="json") for s, _ in snapshots],
                }
            )
            old = await conn.execute(
                "SELECT creation_sha256 FROM paper_audit_runs WHERE run_id=? AND owner_user_id=?",
                (run_id, owner),
            )
            if old:
                if old[0]["creation_sha256"] != fingerprint:
                    raise LifecycleConflict("Run idempotency key has different inputs.")
                return await self._read(conn, owner, project, run_id, ip_hash=ip_hash)
            run = ProjectAuditRun(
                run_id=run_id,
                project_id=project,
                requested_by=owner,
                quota=PaperQuotaPreflight(
                    provider_calls_available=None,
                    requested_links=len(snapshots),
                    runnable_now=0,
                    blocked=len(snapshots),
                ),
                items=[],
            )
            await conn.execute(
                "INSERT INTO paper_audit_runs VALUES(?,?,?,?,?,?)",
                (
                    run_id,
                    project,
                    owner,
                    fingerprint,
                    run.model_dump(mode="json"),
                    run.created_at.isoformat(),
                ),
            )
            for snapshot, _ in snapshots:
                item_id = stable_id(project, "item:" + snapshot.source_link_id)
                item = ProjectAuditRunItem(
                    item_id=item_id,
                    run_id=run_id,
                    project_id=project,
                    claim_source_link_id=snapshot.source_link_id,
                    snapshot=snapshot,
                    input_snapshot_hash=digest(snapshot.model_dump(mode="json")),
                    use_judgment_provider=request.use_judgment_provider,
                )
                previous = await conn.execute(
                    "SELECT record_json FROM paper_audit_items WHERE item_id=? AND owner_user_id=?",
                    (item_id, owner),
                )
                if previous:
                    cached = ProjectAuditRunItem.model_validate(unpack(previous[0]["record_json"]))
                    if (
                        cached.input_snapshot_hash != item.input_snapshot_hash
                        or cached.use_judgment_provider != item.use_judgment_provider
                    ):
                        raise LifecycleConflict(
                            "A source link already has an initial audit input. Use ordinary Audit Revision."
                        )
                else:
                    await conn.execute(
                        "INSERT INTO paper_audit_items(item_id,run_id,project_id,owner_user_id,source_link_id,record_json,requests_json) VALUES(?,?,?,?,?,?,?)",
                        (
                            item_id,
                            run_id,
                            project,
                            owner,
                            snapshot.source_link_id,
                            item.model_dump(mode="json"),
                            {},
                        ),
                    )
                await conn.execute(
                    "INSERT INTO paper_run_members VALUES(?,?,?,?)",
                    (run_id, item_id, project, owner),
                )
            await self.workflow._event(
                conn,
                owner,
                project,
                "audit_run.planned",
                {
                    "run_id": run_id,
                    "input_hashes": [digest(s.model_dump(mode="json")) for s, _ in snapshots],
                },
                run_id,
            )
            return await self._read(conn, owner, project, run_id, ip_hash=ip_hash)

    async def claim(
        self, owner: str, project: str, run: str, item_id: str, request: AuditItemExecute
    ) -> ExecutionClaim:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, project)
            row = await self._row(conn, owner, project, run, item_id)
            item = await self._recover(conn, owner, row)
            keys = unpack(row["requests_json"])
            fingerprint = digest(request.model_dump(mode="json", exclude={"idempotency_key"}))
            if request.input_snapshot_hash != item.input_snapshot_hash or (
                request.idempotency_key in keys and keys[request.idempotency_key] != fingerprint
            ):
                raise LifecycleConflict("Execute idempotency key or input snapshot changed.")
            if item.status in {"completed", "running"}:
                return ExecutionClaim(item=item)
            snapshot, _ = await self.inputs(conn, owner, project, item.claim_source_link_id)
            if digest(snapshot.model_dump(mode="json")) != item.input_snapshot_hash:
                raise LifecycleConflict("Confirmed input changed after run planning.")
            usage = await conn.execute(
                "SELECT status FROM paper_provider_usage WHERE item_id=? AND owner_user_id=? ORDER BY created_at DESC LIMIT 1",
                (item_id, owner),
            )
            if usage and usage[0]["status"] in {"started", "unknown"}:
                item.status, item.error_code, item.retry_allowed = (
                    "failed",
                    "provider_outcome_unknown",
                    False,
                )
                await self._put(conn, owner, item)
                return ExecutionClaim(item=item)
            if item.attempts >= self.MAX_ATTEMPTS:
                item.retry_allowed = False
                await self._put(conn, owner, item)
                return ExecutionClaim(item=item)
            if len(keys) >= 200 and request.idempotency_key not in keys:
                raise LifecycleConflict(
                    "Too many distinct execution keys for this item; reuse an existing key."
                )
            keys[request.idempotency_key] = fingerprint
            lease = str(uuid4())
            item.status, item.error_code, item.retry_allowed = "running", None, True
            item.attempts += 1
            await self._put(conn, owner, item)
            await conn.execute(
                "UPDATE paper_audit_items SET lease_token=?,lease_until=?,requests_json=? WHERE item_id=? AND owner_user_id=?",
                (
                    lease,
                    (utc_now() + timedelta(seconds=self.lease_seconds)).isoformat(),
                    keys,
                    item_id,
                    owner,
                ),
            )
            await self.workflow._event(
                conn,
                owner,
                project,
                "audit_item.started",
                {
                    "run_id": run,
                    "attempt": item.attempts,
                    "input_snapshot_hash": item.input_snapshot_hash,
                },
                item_id,
            )
            checkpoint = (
                ClaimAudit.model_validate(unpack(row["checkpoint_json"]))
                if row["checkpoint_json"]
                else None
            )
            return ExecutionClaim(item=item, lease_token=lease, checkpoint=checkpoint)

    async def checkpoint(self, owner: str, claim: ExecutionClaim, audit: ClaimAudit) -> None:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, claim.item.project_id)
            await self._fence(conn, owner, claim)
            await conn.execute(
                "UPDATE paper_audit_items SET checkpoint_json=? WHERE item_id=? AND owner_user_id=?",
                (audit.model_dump(mode="json"), claim.item.item_id, owner),
            )

    async def _fence(self, conn: _Connection, owner: str, claim: ExecutionClaim) -> None:
        row = await self._row(
            conn, owner, claim.item.project_id, claim.item.run_id, claim.item.item_id
        )
        item = ProjectAuditRunItem.model_validate(unpack(row["record_json"]))
        if row["lease_token"] != claim.lease_token or item.status != "running":
            raise LifecycleConflict("Execution lease is stale.")

    async def complete(
        self, owner: str, claim: ExecutionClaim, audit: ClaimAudit
    ) -> ProjectAuditRunItem:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, claim.item.project_id)
            await self._fence(conn, owner, claim)
            if isinstance(self.audits, PostgresAuditStore):
                await self.audits.save_in_transaction(conn.raw, owner, audit)
            else:
                sqlite_audits = self.audits
                await to_thread.run_sync(
                    lambda: sqlite_audits.legacy_store.save_in_transaction(conn.raw, audit)
                )
            link = ProjectAuditLink(
                audit_link_id=stable_id(
                    claim.item.project_id, "audit-link:" + claim.item.claim_source_link_id
                ),
                project_id=claim.item.project_id,
                claim_source_link_id=claim.item.claim_source_link_id,
                audit_id=audit.audit_id,
            )
            await self.workflow._insert(conn, owner, "audit_link", link, link.claim_source_link_id)
            item = claim.item.model_copy(
                update={
                    "status": "completed",
                    "audit_id": audit.audit_id,
                    "error_code": None,
                    "retry_allowed": False,
                }
            )
            await self._put(conn, owner, item)
            await self.workflow._event(
                conn,
                owner,
                item.project_id,
                "audit_item.completed",
                {
                    "audit_id": audit.audit_id,
                    "run_id": item.run_id,
                    "input_snapshot_hash": item.input_snapshot_hash,
                },
                item.item_id,
            )
            return item

    async def fail(
        self, owner: str, claim: ExecutionClaim, code: str, *, quota: bool = False
    ) -> ProjectAuditRunItem:
        async with self.workflow.transaction() as conn:
            await self.workflow._project(conn, owner, claim.item.project_id)
            await self._fence(conn, owner, claim)
            usage = await conn.execute(
                "SELECT status FROM paper_provider_usage WHERE item_id=? AND owner_user_id=? ORDER BY created_at DESC LIMIT 1",
                (claim.item.item_id, owner),
            )
            unknown = bool(usage and usage[0]["status"] in {"started", "unknown"})
            if unknown:
                await conn.execute(
                    "UPDATE paper_provider_usage SET status='unknown' WHERE item_id=? AND owner_user_id=? AND status='started'",
                    (claim.item.item_id, owner),
                )
            item = claim.item.model_copy(
                update={
                    "status": "quota_blocked" if quota else "failed",
                    "error_code": "provider_outcome_unknown" if unknown else code,
                    "retry_allowed": not unknown and claim.item.attempts < self.MAX_ATTEMPTS,
                }
            )
            # A denied reservation is not an execution attempt and must remain retryable.
            if quota:
                item.attempts -= 1
                item.retry_allowed = True
            await self._put(conn, owner, item)
            await self.workflow._event(
                conn,
                owner,
                item.project_id,
                "audit_item." + item.status,
                {"error_code": item.error_code},
                item.item_id,
            )
            return item

    async def cached(self, owner: str, item: str) -> dict[str, Any] | None:
        async with self.workflow.transaction() as conn:
            rows = await conn.execute(
                "SELECT * FROM paper_provider_usage WHERE owner_user_id=? AND item_id=? ORDER BY created_at DESC LIMIT 1",
                (owner, item),
            )
            return rows[0] if rows else None

    async def reserve(
        self, owner: str, claim: ExecutionClaim, run: str, provider: str, ip_hash: str | None
    ) -> str:
        usage_id = str(uuid4())
        async with self.workflow.transaction() as conn:
            if conn.postgres:
                await conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(?,0))",
                    ("claim-trellis-paper-provider",),
                )
            await self.workflow._project(conn, owner, claim.item.project_id)
            await self._fence(conn, owner, claim)
            # Expired operational leases cannot strand every project's concurrency slot.
            # Abandoned items remain unknown; never automatically re-call them.
            await conn.execute(
                "UPDATE paper_provider_usage SET status='unknown' WHERE status='started' AND item_id IN (SELECT item_id FROM paper_audit_items WHERE lease_until<?)",
                (utc_now().isoformat(),),
            )
            available, reason = await self._budget(conn, owner, run, ip_hash=ip_hash)
            if not available:
                raise PaperBudgetBlocked(reason)
            if conn.postgres and self.settings.auth_mode == "supabase":
                if not ip_hash:
                    raise PaperBudgetBlocked("hosted_provider_unavailable")
                guard = PostgresUsageGuard(self.workflow.pool)
                try:
                    await guard.reserve_in_transaction(
                        conn.raw,
                        owner,
                        ip_hash,
                        provider,
                        "audit",
                        usage_id=usage_id,
                        user_limit=self.settings.paper_daily_user_limit,
                    )
                except HostedUsageLimit as exc:
                    raise PaperBudgetBlocked("hosted_" + exc.scope + "_limit") from exc
            await conn.execute(
                "INSERT INTO paper_provider_usage(usage_id,item_id,run_id,project_id,owner_user_id,lease_token,status,created_at) VALUES(?,?,?,?,?,?,'started',?)",
                (
                    usage_id,
                    claim.item.item_id,
                    run,
                    claim.item.project_id,
                    owner,
                    claim.lease_token,
                    utc_now().isoformat(),
                ),
            )
            await self.workflow._event(
                conn,
                owner,
                claim.item.project_id,
                "audit_item.provider_reserved",
                {"usage_id": usage_id, "run_id": run},
                claim.item.item_id,
            )
        return usage_id

    async def outcome(
        self, usage_id: str, result: JudgmentResult | None, error: str | None
    ) -> None:
        async with self.workflow.transaction() as conn:
            await conn.execute(
                "UPDATE paper_provider_usage SET status=?,result_json=?,error_code=?,completed_at=? WHERE usage_id=? AND status IN ('started','unknown')",
                (
                    "failed" if error else "succeeded",
                    result.model_dump(mode="json") if result else None,
                    error,
                    utc_now().isoformat(),
                    usage_id,
                ),
            )
            if conn.postgres and self.settings.auth_mode == "supabase":
                await conn.execute(
                    "UPDATE provider_usage SET status=?,completed_at=?,input_tokens=?,output_tokens=?,error_code=? WHERE usage_id=? AND status='started'",
                    (
                        "failed" if error else "succeeded",
                        utc_now().isoformat(),
                        result.input_tokens if result else None,
                        result.output_tokens if result else None,
                        error,
                        usage_id,
                    ),
                )

    async def execute(
        self,
        owner: str,
        project: str,
        run: str,
        item: str,
        request: AuditItemExecute,
        provider: JudgmentProvider | None,
        ip_hash: str | None = None,
    ) -> ProjectAuditRunItem:
        claimed = await self.claim(owner, project, run, item, request)
        if claimed.lease_token is None:
            return claimed.item
        try:
            audit = claimed.checkpoint
            if audit is None:
                async with self.workflow.transaction() as conn:
                    _, audit_request = await self.inputs(
                        conn, owner, project, claimed.item.claim_source_link_id
                    )
                audit_request.use_judgment_provider = claimed.item.use_judgment_provider
                if audit_request.use_judgment_provider and provider is None:
                    raise PaperBudgetBlocked("provider_unavailable")
                adapter = (
                    PaperProvider(self, claimed, owner, run, provider, ip_hash)
                    if provider is not None
                    else None
                )
                audit = await run_audit(
                    audit_request,
                    self.settings.model_copy(update={"auto_accept_enabled": False}),
                    judgment_provider=adapter,
                )
                audit.audit_id = stable_id(
                    project, "initial-audit:" + claimed.item.claim_source_link_id
                )
                audit.provenance.parser_version = claimed.item.snapshot.parser_version
                await self.checkpoint(owner, claimed, audit)
            return await self.complete(owner, claimed, audit)
        except PaperBudgetBlocked as exc:
            return await self.fail(owner, claimed, str(exc), quota=True)
        except asyncio.CancelledError:
            await asyncio.shield(self.fail(owner, claimed, "execution_interrupted"))
            raise
        except LifecycleConflict:
            raise
        except Exception:
            return await self.fail(owner, claimed, "execution_failed")


class PaperProvider:
    """Calls the existing provider unchanged, caching terminal outcomes before P0 consumes them."""

    def __init__(
        self,
        store: PaperRunStore,
        claim: ExecutionClaim,
        owner: str,
        run: str,
        provider: JudgmentProvider,
        ip_hash: str | None,
    ) -> None:
        self.store, self.claim, self.owner, self.run, self.provider, self.ip_hash = (
            store,
            claim,
            owner,
            run,
            provider,
            ip_hash,
        )
        self.provider_name, self.model_name, self.question_set_version = (
            provider.provider_name,
            provider.model_name,
            provider.question_set_version,
        )

    async def evaluate(
        self,
        claim: str,
        evidence: str,
        citation: str | None = None,
        *,
        revision_context: RevisionContext | None = None,
    ) -> JudgmentResult:
        cached = await self.store.cached(self.owner, self.claim.item.item_id)
        if cached:
            if cached["result_json"]:
                return JudgmentResult.model_validate(unpack(cached["result_json"]))
            if cached["status"] == "failed":
                raise ProviderError("Paper provider evaluation failed.")
            raise PaperBudgetBlocked("provider_outcome_unknown")
        usage = await self.store.reserve(
            self.owner, self.claim, self.run, self.provider_name, self.ip_hash
        )
        try:
            result = await self.provider.evaluate(
                claim, evidence, citation, revision_context=revision_context
            )
        except ProviderError:
            await self.store.outcome(usage, None, "provider_error")
            raise ProviderError("Paper provider evaluation failed.") from None
        except TimeoutError:
            await self.store.outcome(usage, None, "timeout")
            raise ProviderError("Paper provider timed out.") from None
        # Other interruptions leave an unknown reservation: never automatically re-call.
        await self.store.outcome(usage, result, None)
        return result
