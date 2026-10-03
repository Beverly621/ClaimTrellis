"""Ownership-scoped, transactional PostgreSQL audit lifecycle storage."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from claim_trellis.audit_fidelity import complete_evidence_revision, initial_events
from claim_trellis.evidence_sets import revision_evidence
from claim_trellis.models import (
    AuditEvent,
    ClaimAudit,
    HumanDecision,
    HumanReview,
    HumanReviewRequest,
    JudgmentResult,
    Proposal,
    ProposalVersion,
    RelationLabel,
    ReviewStatus,
    RevisionRequest,
    RevisionRun,
    RevisionStatus,
    utc_now,
)
from claim_trellis.storage import AuditStore, LifecycleConflict


class PostgresAuditStore:
    """One small async pool per warm app; correctness lives in DB transactions."""

    REVISION_LEASE_SECONDS = 180

    def __init__(self, database_url: str, *, sslmode: str = "require") -> None:
        conninfo = make_conninfo(database_url, sslmode=sslmode)
        self.pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] = AsyncConnectionPool(
            conninfo,
            kwargs={"prepare_threshold": None, "row_factory": dict_row},
            min_size=0,
            max_size=1,
            open=False,
            check=AsyncConnectionPool.check_connection,
        )

    async def open(self) -> None:
        await self.pool.open()

    async def close(self) -> None:
        await self.pool.close()

    @staticmethod
    async def _locked(conn: Any, owner: str, audit_id: str) -> ClaimAudit:
        result = await conn.execute(
            "SELECT record_json FROM audits WHERE audit_id=%s AND owner_user_id=%s FOR UPDATE",
            (audit_id, owner),
        )
        row = await result.fetchone()
        if row is None:
            raise KeyError(audit_id)
        return ClaimAudit.model_validate(row["record_json"])

    @staticmethod
    async def _write(conn: Any, owner: str, audit: ClaimAudit) -> None:
        await conn.execute(
            "UPDATE audits SET updated_at=%s, record_json=%s "
            "WHERE audit_id=%s AND owner_user_id=%s",
            (utc_now(), Jsonb(audit.model_dump(mode="json")), audit.audit_id, owner),
        )

    async def _event(
        self,
        conn: Any,
        owner: str,
        audit: ClaimAudit,
        name: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        data = {
            "audit_id": audit.audit_id,
            "proposal_id": audit.current_proposal_id,
            "proposal_version": audit.current_proposal_version,
            **(payload or {}),
        }
        await conn.execute(
            "INSERT INTO audit_events "
            "(event_id,audit_id,owner_user_id,event_type,created_at,payload_json) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (str(uuid4()), audit.audit_id, owner, name, utc_now(), Jsonb(data)),
        )

    async def _create_version(
        self,
        conn: Any,
        owner: str,
        audit: ClaimAudit,
        parent_id: str | None = None,
        *,
        emit_event: bool = True,
    ) -> ProposalVersion:
        judgment = audit.judgment_result
        snapshot = ProposalVersion(
            audit_id=audit.audit_id,
            proposal_id=str(uuid4()),
            version=audit.current_proposal_version,
            parent_proposal_id=parent_id,
            relation=RelationLabel(judgment.relation.choice) if judgment else None,
            probabilities=judgment.relation.probabilities if judgment else {},
            policy=audit.proposal,
            judgment=judgment,
            evidence_set=audit.evidence_set,
            deterministic_checks=audit.deterministic_checks,
            provenance=audit.provenance,
        )
        await conn.execute(
            "INSERT INTO proposal_versions "
            "(proposal_id,audit_id,owner_user_id,version,snapshot_json,review_status,created_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                snapshot.proposal_id,
                audit.audit_id,
                owner,
                snapshot.version,
                Jsonb(snapshot.model_dump(mode="json")),
                audit.review_status,
                snapshot.created_at,
            ),
        )
        audit.current_proposal_id = snapshot.proposal_id
        await self._write(conn, owner, audit)
        if emit_event:
            await self._event(
                conn,
                owner,
                audit,
                "proposal.created",
                {"proposal": snapshot.model_dump(mode="json")},
            )
        return snapshot

    async def save(self, owner_user_id: str, audit: ClaimAudit) -> ClaimAudit:
        async with self.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO audits "
                "(audit_id,owner_user_id,created_at,updated_at,record_json) "
                "VALUES (%s,%s,%s,%s,%s)",
                (
                    audit.audit_id,
                    owner_user_id,
                    audit.provenance.created_at,
                    utc_now(),
                    Jsonb(audit.model_dump(mode="json")),
                ),
            )
            snapshot = await self._create_version(conn, owner_user_id, audit, emit_event=False)
            await self._event(
                conn, owner_user_id, audit, "audit.created", audit.model_dump(mode="json")
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "source.loaded",
                {"source": audit.source.model_dump(mode="json")},
            )
            for name, payload in initial_events(audit):
                await self._event(conn, owner_user_id, audit, name, payload)
            await self._event(
                conn,
                owner_user_id,
                audit,
                "checks.completed",
                {"checks": audit.deterministic_checks.model_dump(mode="json")},
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "judgment.completed",
                {
                    "judgment": audit.judgment_result.model_dump(mode="json")
                    if audit.judgment_result
                    else None
                },
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "proposal.created",
                {"proposal": snapshot.model_dump(mode="json")},
            )
        return audit

    async def _status(self, conn: Any, owner: str, audit: ClaimAudit, status: ReviewStatus) -> None:
        audit.review_status = status
        audit.state_revision += 1
        await conn.execute(
            "UPDATE proposal_versions SET review_status=%s "
            "WHERE proposal_id=%s AND audit_id=%s AND owner_user_id=%s",
            (status, audit.current_proposal_id, audit.audit_id, owner),
        )
        await self._write(conn, owner, audit)

    async def _fail_locked(
        self,
        conn: Any,
        owner: str,
        audit: ClaimAudit,
        run: RevisionRun,
        code: str,
        message: str,
    ) -> RevisionRun:
        if run.status not in {RevisionStatus.REQUESTED, RevisionStatus.RUNNING}:
            return run
        run.status = RevisionStatus.FAILED
        run.error_code = code
        run.error_message = message
        run.updated_at = utc_now()
        await conn.execute(
            "UPDATE revision_runs SET record_json=%s,status=%s,updated_at=%s "
            "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s",
            (
                Jsonb(run.model_dump(mode="json")),
                run.status,
                run.updated_at,
                run.revision_id,
                audit.audit_id,
                owner,
            ),
        )
        audit.service_errors = [message]
        await self._status(conn, owner, audit, ReviewStatus.FAILED)
        await self._event(
            conn,
            owner,
            audit,
            "revision.failed",
            {"revision_id": run.revision_id, "error_code": code, "message": message},
        )
        return run

    async def _recover_locked(self, conn: Any, owner: str, audit: ClaimAudit) -> None:
        cutoff = utc_now() - timedelta(seconds=self.REVISION_LEASE_SECONDS)
        rows = await conn.execute(
            "SELECT record_json FROM revision_runs "
            "WHERE audit_id=%s AND owner_user_id=%s "
            "AND status IN ('revision_requested','revision_running') AND updated_at < %s "
            "ORDER BY revision_seq FOR UPDATE",
            (audit.audit_id, owner, cutoff),
        )
        for row in await rows.fetchall():
            await self._fail_locked(
                conn,
                owner,
                audit,
                RevisionRun.model_validate(row["record_json"]),
                "interrupted",
                "Evaluation did not complete. Your feedback is preserved; retry the revision.",
            )

    async def get(self, owner_user_id: str, audit_id: str) -> ClaimAudit | None:
        async with self.pool.connection() as conn:
            try:
                audit = await self._locked(conn, owner_user_id, audit_id)
            except KeyError:
                return None
            await self._recover_locked(conn, owner_user_id, audit)
            return audit

    async def list_audits(
        self, owner_user_id: str, *, limit: int = 50, offset: int = 0
    ) -> list[ClaimAudit]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT audit_id FROM audits WHERE owner_user_id=%s "
                "ORDER BY created_at DESC,audit_id DESC LIMIT %s OFFSET %s",
                (owner_user_id, limit, offset),
            )
            ids = [row["audit_id"] for row in await result.fetchall()]
        return [audit for audit_id in ids if (audit := await self.get(owner_user_id, audit_id))]

    async def proposals(self, owner_user_id: str, audit_id: str) -> list[ProposalVersion]:
        if await self.get(owner_user_id, audit_id) is None:
            raise KeyError(audit_id)
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT snapshot_json,review_status FROM proposal_versions "
                "WHERE audit_id=%s AND owner_user_id=%s ORDER BY version",
                (audit_id, owner_user_id),
            )
            rows = await result.fetchall()
        return [
            ProposalVersion.model_validate(row["snapshot_json"]).model_copy(
                update={"review_status": ReviewStatus(row["review_status"])}
            )
            for row in rows
        ]

    async def review(
        self, owner_user_id: str, audit_id: str, request: HumanReviewRequest
    ) -> ClaimAudit:
        async with self.pool.connection() as conn:
            audit = await self._locked(conn, owner_user_id, audit_id)
            await self._recover_locked(conn, owner_user_id, audit)
            AuditStore._guard(
                audit,
                request.proposal_id,
                request.proposal_version,
                request.expected_state_revision,
            )
            if audit.review_status in {
                ReviewStatus.ACCEPTED,
                ReviewStatus.REJECTED,
                ReviewStatus.REQUESTED,
                ReviewStatus.RUNNING,
            }:
                raise LifecycleConflict("This proposal is finalized or has an active revision.")
            if request.decision == HumanDecision.REVISE:
                raise LifecycleConflict("Use POST /revisions with feedback and an idempotency key.")
            if request.decision == HumanDecision.ACCEPT and (
                audit.review_status == ReviewStatus.FAILED or audit.service_errors
            ):
                raise LifecycleConflict("Resolve the provider failure before accepting.")
            audit.human_review = HumanReview(
                decision=request.decision,
                notes=request.notes,
                reviewer=request.reviewer,
                proposal_id=audit.current_proposal_id,
                proposal_version=audit.current_proposal_version,
            )
            await self._status(
                conn, owner_user_id, audit, AuditStore._review_status(request.decision)
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "feedback.recorded",
                {"reviewer": request.reviewer, "feedback": request.notes},
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                f"review.{audit.review_status}",
                {"review": audit.human_review.model_dump(mode="json")},
            )
            return audit

    async def request_revision(
        self, owner_user_id: str, audit_id: str, request: RevisionRequest
    ) -> tuple[RevisionRun, bool]:
        async with self.pool.connection() as conn:
            audit = await self._locked(conn, owner_user_id, audit_id)
            await self._recover_locked(conn, owner_user_id, audit)
            result = await conn.execute(
                "SELECT record_json FROM revision_runs "
                "WHERE audit_id=%s AND owner_user_id=%s AND idempotency_key=%s",
                (audit_id, owner_user_id, request.idempotency_key),
            )
            existing = await result.fetchone()
            if existing is not None:
                run = RevisionRun.model_validate(existing["record_json"])
                if run.request != request:
                    raise LifecycleConflict(
                        "Idempotency key was already used with different input."
                    )
                return run, False
            AuditStore._guard(
                audit,
                request.proposal_id,
                request.proposal_version,
                request.expected_state_revision,
            )
            if audit.review_status in {
                ReviewStatus.ACCEPTED,
                ReviewStatus.REQUESTED,
                ReviewStatus.RUNNING,
            }:
                raise LifecycleConflict("This proposal is finalized or has an active revision.")
            try:
                revision_evidence(audit, request)
            except ValueError as exc:
                raise LifecycleConflict(str(exc)) from exc
            run = RevisionRun(
                revision_id=str(uuid4()),
                audit_id=audit_id,
                request=request,
                status=RevisionStatus.REQUESTED,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            parent_status = audit.review_status
            if parent_status == ReviewStatus.FAILED:
                previous = await conn.execute(
                    "SELECT parent_status FROM revision_runs "
                    "WHERE audit_id=%s AND owner_user_id=%s ORDER BY revision_seq DESC LIMIT 1",
                    (audit_id, owner_user_id),
                )
                row = await previous.fetchone()
                if row:
                    parent_status = ReviewStatus(row["parent_status"])
            await conn.execute(
                "INSERT INTO revision_runs "
                "(revision_id,audit_id,owner_user_id,idempotency_key,record_json,parent_status,"
                "status,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    run.revision_id,
                    audit_id,
                    owner_user_id,
                    request.idempotency_key,
                    Jsonb(run.model_dump(mode="json")),
                    parent_status,
                    run.status,
                    run.created_at,
                    run.updated_at,
                ),
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "feedback.recorded",
                {
                    "revision_id": run.revision_id,
                    "reviewer": request.reviewer,
                    "feedback": request.feedback,
                },
            )
            audit.human_review = None
            await self._status(conn, owner_user_id, audit, ReviewStatus.REQUESTED)
            await self._event(
                conn,
                owner_user_id,
                audit,
                "revision.requested",
                {"revision_id": run.revision_id, "reviewer": request.reviewer},
            )
            return run, True

    async def start_revision(self, owner_user_id: str, run: RevisionRun) -> None:
        async with self.pool.connection() as conn:
            audit = await self._locked(conn, owner_user_id, run.audit_id)
            result = await conn.execute(
                "SELECT record_json FROM revision_runs "
                "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s FOR UPDATE",
                (run.revision_id, run.audit_id, owner_user_id),
            )
            row = await result.fetchone()
            if (
                row is None
                or RevisionRun.model_validate(row["record_json"]).status != RevisionStatus.REQUESTED
            ):
                raise LifecycleConflict("Revision is no longer current.")
            if (
                audit.review_status != ReviewStatus.REQUESTED
                or audit.current_proposal_id != run.request.proposal_id
            ):
                raise LifecycleConflict("Revision is no longer current.")
            run.status = RevisionStatus.RUNNING
            run.updated_at = utc_now()
            await conn.execute(
                "UPDATE revision_runs SET record_json=%s,status=%s,updated_at=%s "
                "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s",
                (
                    Jsonb(run.model_dump(mode="json")),
                    run.status,
                    run.updated_at,
                    run.revision_id,
                    run.audit_id,
                    owner_user_id,
                ),
            )
            await self._status(conn, owner_user_id, audit, ReviewStatus.RUNNING)
            await self._event(
                conn, owner_user_id, audit, "revision.started", {"revision_id": run.revision_id}
            )

    async def finish_revision(
        self,
        owner_user_id: str,
        run: RevisionRun,
        judgment: JudgmentResult | None,
        policy: Proposal,
    ) -> RevisionRun:
        async with self.pool.connection() as conn:
            audit = await self._locked(conn, owner_user_id, run.audit_id)
            result = await conn.execute(
                "SELECT record_json,parent_status FROM revision_runs "
                "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s FOR UPDATE",
                (run.revision_id, run.audit_id, owner_user_id),
            )
            row = await result.fetchone()
            if row is None:
                raise KeyError(run.audit_id)
            stored = RevisionRun.model_validate(row["record_json"])
            if stored.status != RevisionStatus.RUNNING:
                return stored
            if audit.current_proposal_id != run.request.proposal_id:
                raise LifecycleConflict("Revision parent is no longer current.")
            parent_status = (
                ReviewStatus.REJECTED
                if row["parent_status"] == ReviewStatus.REJECTED
                else ReviewStatus.SUPERSEDED
            )
            await conn.execute(
                "UPDATE proposal_versions SET review_status=%s "
                "WHERE proposal_id=%s AND audit_id=%s AND owner_user_id=%s",
                (parent_status, audit.current_proposal_id, audit.audit_id, owner_user_id),
            )
            if parent_status == ReviewStatus.SUPERSEDED:
                await self._event(
                    conn,
                    owner_user_id,
                    audit,
                    "proposal.superseded",
                    {"revision_id": run.revision_id},
                )
            parent = audit.current_proposal_id
            audit.current_proposal_version += 1
            audit.review_status = ReviewStatus.PENDING
            audit.state_revision += 1
            audit.human_review = None
            audit.judgment_result = judgment
            audit.proposal = policy
            audit.service_errors = []
            changed = complete_evidence_revision(audit, stored.request, judgment, policy)
            snapshot = await self._create_version(
                conn, owner_user_id, audit, parent, emit_event=False
            )
            if changed:
                await self._event(conn, owner_user_id, audit, "evidence.selection.changed", changed)
            await self._event(
                conn,
                owner_user_id,
                audit,
                "checks.completed",
                {"checks": audit.deterministic_checks.model_dump(mode="json")},
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "judgment.completed",
                {"judgment": judgment.model_dump(mode="json") if judgment else None},
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "proposal.created",
                {"proposal": snapshot.model_dump(mode="json")},
            )
            run.status = RevisionStatus.COMPLETED
            run.result_proposal_id = snapshot.proposal_id
            run.updated_at = utc_now()
            await conn.execute(
                "UPDATE revision_runs SET record_json=%s,status=%s,updated_at=%s "
                "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s",
                (
                    Jsonb(run.model_dump(mode="json")),
                    run.status,
                    run.updated_at,
                    run.revision_id,
                    run.audit_id,
                    owner_user_id,
                ),
            )
            await self._event(
                conn,
                owner_user_id,
                audit,
                "revision.completed",
                {
                    "revision_id": run.revision_id,
                    "parent_proposal_id": parent,
                    "provider": judgment.provider if judgment else None,
                    "model": judgment.resolved_model if judgment else None,
                },
            )
            return run

    async def fail_revision(
        self, owner_user_id: str, run: RevisionRun, code: str, message: str
    ) -> RevisionRun:
        async with self.pool.connection() as conn:
            audit = await self._locked(conn, owner_user_id, run.audit_id)
            result = await conn.execute(
                "SELECT record_json FROM revision_runs "
                "WHERE revision_id=%s AND audit_id=%s AND owner_user_id=%s FOR UPDATE",
                (run.revision_id, run.audit_id, owner_user_id),
            )
            row = await result.fetchone()
            if row is None:
                raise KeyError(run.audit_id)
            stored = RevisionRun.model_validate(row["record_json"])
            return await self._fail_locked(conn, owner_user_id, audit, stored, code, message)

    async def revisions(self, owner_user_id: str, audit_id: str) -> list[RevisionRun]:
        if await self.get(owner_user_id, audit_id) is None:
            raise KeyError(audit_id)
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT record_json FROM revision_runs "
                "WHERE audit_id=%s AND owner_user_id=%s ORDER BY revision_seq",
                (audit_id, owner_user_id),
            )
            rows = await result.fetchall()
        return [RevisionRun.model_validate(row["record_json"]) for row in rows]

    async def events(self, owner_user_id: str, audit_id: str) -> list[AuditEvent]:
        if await self.get(owner_user_id, audit_id) is None:
            raise KeyError(audit_id)
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT event_id,audit_id,event_type,created_at,payload_json "
                "FROM audit_events WHERE audit_id=%s AND owner_user_id=%s ORDER BY event_seq",
                (audit_id, owner_user_id),
            )
            rows = await result.fetchall()
        return [
            AuditEvent(
                event_id=row["event_id"],
                audit_id=row["audit_id"],
                event_type=row["event_type"],
                created_at=row["created_at"],
                payload=row["payload_json"],
                proposal_id=row["payload_json"].get("proposal_id"),
                proposal_version=row["payload_json"].get("proposal_version"),
            )
            for row in rows
        ]
