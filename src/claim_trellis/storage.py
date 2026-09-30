from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

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


class LifecycleConflict(ValueError):
    """The request targets stale or incompatible lifecycle state."""


class AuditStore:
    REVISION_LEASE_SECONDS = 180

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS audits (
                    audit_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, record_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit_events (
                    event_id TEXT PRIMARY KEY, audit_id TEXT NOT NULL,
                    event_type TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL,
                    FOREIGN KEY (audit_id) REFERENCES audits(audit_id));
                CREATE INDEX IF NOT EXISTS idx_audit_events_audit_id
                    ON audit_events(audit_id, created_at);
                CREATE TABLE IF NOT EXISTS proposal_versions (
                    proposal_id TEXT PRIMARY KEY, audit_id TEXT NOT NULL,
                    version INTEGER NOT NULL, snapshot_json TEXT NOT NULL, review_status TEXT NOT NULL,
                    UNIQUE(audit_id, version),
                    FOREIGN KEY (audit_id) REFERENCES audits(audit_id));
                CREATE TABLE IF NOT EXISTS revision_runs (
                    revision_id TEXT PRIMARY KEY, audit_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL, record_json TEXT NOT NULL, parent_status TEXT NOT NULL,
                    UNIQUE(audit_id, idempotency_key),
                    FOREIGN KEY (audit_id) REFERENCES audits(audit_id));
            """)
            c.execute("BEGIN IMMEDIATE")
            for row in c.execute("SELECT record_json FROM audits").fetchall():
                audit = ClaimAudit.model_validate_json(row[0])
                if audit.current_proposal_id is None:
                    if audit.human_review:
                        audit.review_status = self._review_status(audit.human_review.decision)
                        audit.state_revision = 1
                    self._create_version(c, audit, legacy=True)

    @staticmethod
    def _review_status(decision: HumanDecision) -> ReviewStatus:
        return {
            HumanDecision.ACCEPT: ReviewStatus.ACCEPTED,
            HumanDecision.REJECT: ReviewStatus.REJECTED,
            HumanDecision.DEFER: ReviewStatus.DEFERRED,
            HumanDecision.REVISE: ReviewStatus.PENDING,
        }[decision]

    def _write(self, c: sqlite3.Connection, audit: ClaimAudit) -> None:
        c.execute(
            "UPDATE audits SET updated_at=?, record_json=? WHERE audit_id=?",
            (utc_now().isoformat(), audit.model_dump_json(), audit.audit_id),
        )

    def _event(
        self,
        c: sqlite3.Connection,
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
        c.execute(
            "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                audit.audit_id,
                name,
                utc_now().isoformat(),
                json.dumps(data, ensure_ascii=False, separators=(",", ":")),
            ),
        )

    def _create_version(
        self,
        c: sqlite3.Connection,
        audit: ClaimAudit,
        parent_id: str | None = None,
        *,
        legacy: bool = False,
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
            created_at=audit.provenance.created_at if legacy else utc_now(),
        )
        c.execute(
            "INSERT INTO proposal_versions VALUES (?, ?, ?, ?, ?)",
            (
                snapshot.proposal_id,
                audit.audit_id,
                snapshot.version,
                snapshot.model_dump_json(),
                audit.review_status,
            ),
        )
        audit.current_proposal_id = snapshot.proposal_id
        self._write(c, audit)
        if emit_event:
            self._event(
                c,
                audit,
                "proposal.created",
                {"proposal": snapshot.model_dump(mode="json"), "legacy_migration": legacy},
            )
        return snapshot

    def save(self, audit: ClaimAudit, *, event_type: str = "audit.created") -> ClaimAudit:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            # No upsert: existing snapshots may only change through lifecycle operations.
            c.execute(
                "INSERT INTO audits VALUES (?, ?, ?, ?)",
                (
                    audit.audit_id,
                    audit.provenance.created_at.isoformat(),
                    utc_now().isoformat(),
                    audit.model_dump_json(),
                ),
            )
            snapshot = self._create_version(c, audit, emit_event=False)
            self._event(c, audit, event_type, audit.model_dump(mode="json"))
            self._event(c, audit, "source.loaded", {"source": audit.source.model_dump(mode="json")})
            self._event(
                c,
                audit,
                "checks.completed",
                {"checks": audit.deterministic_checks.model_dump(mode="json")},
            )
            self._event(
                c, audit, "proposal.created", {"proposal": snapshot.model_dump(mode="json")}
            )
        return audit

    @staticmethod
    def _get(c: sqlite3.Connection, audit_id: str) -> ClaimAudit:
        row = c.execute("SELECT record_json FROM audits WHERE audit_id=?", (audit_id,)).fetchone()
        if row is None:
            raise KeyError(audit_id)
        return ClaimAudit.model_validate_json(row[0])

    def get(self, audit_id: str) -> ClaimAudit | None:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            self._recover(c, audit_id)
            try:
                return self._get(c, audit_id)
            except KeyError:
                return None

    def list_audits(self, *, limit: int = 50, offset: int = 0) -> list[ClaimAudit]:
        with self._connect() as c:
            ids = c.execute(
                "SELECT audit_id FROM audits ORDER BY created_at DESC, audit_id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [audit for row in ids if (audit := self.get(row[0])) is not None]

    def proposals(self, audit_id: str) -> list[ProposalVersion]:
        self.get(audit_id)
        with self._connect() as c:
            rows = c.execute(
                "SELECT snapshot_json, review_status FROM proposal_versions WHERE audit_id=? ORDER BY version",
                (audit_id,),
            ).fetchall()
        return [
            ProposalVersion.model_validate_json(row[0]).model_copy(
                update={"review_status": ReviewStatus(row[1])}
            )
            for row in rows
        ]

    @staticmethod
    def _guard(
        audit: ClaimAudit, proposal_id: str | None, version: int | None, expected: int | None
    ) -> None:
        if proposal_id is None and version is None and expected is None:
            # Unversioned v0.1 clients may review an untouched v1 only.
            if audit.current_proposal_version == 1 and audit.state_revision == 0:
                return
        elif (
            proposal_id == audit.current_proposal_id
            and version == audit.current_proposal_version
            and expected == audit.state_revision
        ):
            return
        raise LifecycleConflict("The proposal or review state changed. Reload before continuing.")

    def _status(self, c: sqlite3.Connection, audit: ClaimAudit, status: ReviewStatus) -> None:
        audit.review_status = status
        audit.state_revision += 1
        c.execute(
            "UPDATE proposal_versions SET review_status=? WHERE proposal_id=?",
            (status, audit.current_proposal_id),
        )
        self._write(c, audit)

    def review(self, audit_id: str, request: HumanReviewRequest) -> ClaimAudit:
        self.get(audit_id)  # Commit lease recovery before checking stale state.
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            audit = self._get(c, audit_id)
            self._guard(
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
            if request.decision == HumanDecision.ACCEPT:
                if audit.review_status == ReviewStatus.REJECTED:
                    raise LifecycleConflict(
                        "A rejected proposal needs a new revision before acceptance."
                    )
                if audit.review_status == ReviewStatus.FAILED or audit.service_errors:
                    raise LifecycleConflict("Resolve the provider failure before accepting.")
            audit.human_review = HumanReview(
                decision=request.decision,
                notes=request.notes,
                reviewer=request.reviewer,
                proposal_id=audit.current_proposal_id,
                proposal_version=audit.current_proposal_version,
            )
            self._status(c, audit, self._review_status(request.decision))
            self._event(
                c,
                audit,
                "feedback.recorded",
                {"reviewer": request.reviewer, "feedback": request.notes},
            )
            self._event(
                c,
                audit,
                f"review.{audit.review_status}",
                {"review": audit.human_review.model_dump(mode="json")},
            )
            return audit

    def add_review(self, audit_id: str, review: HumanReview) -> ClaimAudit | None:
        if self.get(audit_id) is None:
            return None
        return self.review(
            audit_id,
            HumanReviewRequest(
                decision=review.decision, notes=review.notes, reviewer=review.reviewer
            ),
        )

    def _put_run(self, c: sqlite3.Connection, run: RevisionRun) -> None:
        c.execute(
            "UPDATE revision_runs SET record_json=? WHERE revision_id=?",
            (run.model_dump_json(), run.revision_id),
        )

    def request_revision(self, audit_id: str, request: RevisionRequest) -> tuple[RevisionRun, bool]:
        self.get(audit_id)
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            audit = self._get(c, audit_id)
            existing = c.execute(
                "SELECT record_json FROM revision_runs WHERE audit_id=? AND idempotency_key=?",
                (audit_id, request.idempotency_key),
            ).fetchone()
            if existing:
                run = RevisionRun.model_validate_json(existing[0])
                if run.request != request:
                    raise LifecycleConflict(
                        "Idempotency key was already used with different input."
                    )
                return run, False
            self._guard(
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
            run = RevisionRun(
                revision_id=str(uuid4()),
                audit_id=audit_id,
                request=request,
                status=RevisionStatus.REQUESTED,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            # Preserve rejection through failures and retries.
            parent_status = audit.review_status
            if parent_status == ReviewStatus.FAILED:
                previous = c.execute(
                    "SELECT parent_status FROM revision_runs WHERE audit_id=? ORDER BY rowid DESC LIMIT 1",
                    (audit_id,),
                ).fetchone()
                if previous:
                    parent_status = ReviewStatus(previous[0])
            c.execute(
                "INSERT INTO revision_runs VALUES (?, ?, ?, ?, ?)",
                (
                    run.revision_id,
                    audit_id,
                    request.idempotency_key,
                    run.model_dump_json(),
                    parent_status,
                ),
            )
            self._event(
                c,
                audit,
                "feedback.recorded",
                {
                    "revision_id": run.revision_id,
                    "reviewer": request.reviewer,
                    "feedback": request.feedback,
                },
            )
            audit.human_review = None
            self._status(c, audit, ReviewStatus.REQUESTED)
            self._event(
                c,
                audit,
                "revision.requested",
                {"revision_id": run.revision_id, "reviewer": request.reviewer},
            )
            return run, True

    def start_revision(self, run: RevisionRun) -> None:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT record_json FROM revision_runs WHERE revision_id=?", (run.revision_id,)
            ).fetchone()
            if (
                row is None
                or RevisionRun.model_validate_json(row[0]).status != RevisionStatus.REQUESTED
            ):
                raise LifecycleConflict("Revision is no longer current.")
            audit = self._get(c, run.audit_id)
            if (
                audit.review_status != ReviewStatus.REQUESTED
                or audit.current_proposal_id != run.request.proposal_id
            ):
                raise LifecycleConflict("Revision is no longer current.")
            run.status = RevisionStatus.RUNNING
            run.updated_at = utc_now()
            self._put_run(c, run)
            self._status(c, audit, ReviewStatus.RUNNING)
            self._event(c, audit, "revision.started", {"revision_id": run.revision_id})

    def finish_revision(
        self, run: RevisionRun, judgment: JudgmentResult, policy: Proposal
    ) -> RevisionRun:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute(
                "SELECT record_json, parent_status FROM revision_runs WHERE revision_id=?",
                (run.revision_id,),
            ).fetchone()
            stored = RevisionRun.model_validate_json(row[0])
            if stored.status != RevisionStatus.RUNNING:
                return stored
            audit = self._get(c, run.audit_id)
            if audit.current_proposal_id != run.request.proposal_id:
                raise LifecycleConflict("Revision parent is no longer current.")
            parent_status = (
                ReviewStatus.REJECTED
                if row[1] == ReviewStatus.REJECTED
                else ReviewStatus.SUPERSEDED
            )
            c.execute(
                "UPDATE proposal_versions SET review_status=? WHERE proposal_id=?",
                (parent_status, audit.current_proposal_id),
            )
            if parent_status == ReviewStatus.SUPERSEDED:
                self._event(c, audit, "proposal.superseded", {"revision_id": run.revision_id})
            parent = audit.current_proposal_id
            audit.current_proposal_version += 1
            audit.review_status = ReviewStatus.PENDING
            audit.state_revision += 1
            audit.human_review = None
            audit.judgment_result = judgment
            audit.proposal = policy
            audit.service_errors = []
            audit.provenance = audit.provenance.model_copy(
                update={
                    "judgment_provider": judgment.provider,
                    "question_set_version": judgment.question_set_version,
                    "policy_version": policy.policy_version,
                }
            )
            snapshot = self._create_version(c, audit, parent)
            run.status = RevisionStatus.COMPLETED
            run.result_proposal_id = snapshot.proposal_id
            run.updated_at = utc_now()
            self._put_run(c, run)
            self._event(
                c,
                audit,
                "revision.completed",
                {
                    "revision_id": run.revision_id,
                    "parent_proposal_id": parent,
                    "provider": judgment.provider,
                    "model": judgment.resolved_model,
                },
            )
            return run

    def fail_revision(self, run: RevisionRun, code: str, message: str) -> RevisionRun:
        with self._connect() as c:
            c.execute("BEGIN IMMEDIATE")
            return self._fail(c, run, code, message)

    def _fail(
        self, c: sqlite3.Connection, run: RevisionRun, code: str, message: str
    ) -> RevisionRun:
        row = c.execute(
            "SELECT record_json FROM revision_runs WHERE revision_id=?", (run.revision_id,)
        ).fetchone()
        stored = RevisionRun.model_validate_json(row[0])
        if stored.status not in {RevisionStatus.REQUESTED, RevisionStatus.RUNNING}:
            return stored
        run.status = RevisionStatus.FAILED
        run.error_code = code
        run.error_message = message
        run.updated_at = utc_now()
        self._put_run(c, run)
        audit = self._get(c, run.audit_id)
        audit.service_errors = [message]
        self._status(c, audit, ReviewStatus.FAILED)
        self._event(
            c,
            audit,
            "revision.failed",
            {"revision_id": run.revision_id, "error_code": code, "message": message},
        )
        return run

    def _recover(self, c: sqlite3.Connection, audit_id: str) -> None:
        for row in c.execute(
            "SELECT record_json FROM revision_runs WHERE audit_id=?", (audit_id,)
        ).fetchall():
            run = RevisionRun.model_validate_json(row[0])
            if run.status in {
                RevisionStatus.REQUESTED,
                RevisionStatus.RUNNING,
            } and utc_now() - run.updated_at > timedelta(seconds=self.REVISION_LEASE_SECONDS):
                self._fail(
                    c,
                    run,
                    "interrupted",
                    "Evaluation did not complete. Your feedback is preserved; retry the revision.",
                )

    def revisions(self, audit_id: str) -> list[RevisionRun]:
        self.get(audit_id)
        with self._connect() as c:
            rows = c.execute(
                "SELECT record_json FROM revision_runs WHERE audit_id=? ORDER BY rowid", (audit_id,)
            ).fetchall()
        return [RevisionRun.model_validate_json(row[0]) for row in rows]

    def events(self, audit_id: str) -> list[AuditEvent]:
        self.get(audit_id)
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM audit_events WHERE audit_id=? ORDER BY rowid", (audit_id,)
            ).fetchall()
        events = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            events.append(
                AuditEvent(
                    event_id=row["event_id"],
                    audit_id=row["audit_id"],
                    event_type=row["event_type"],
                    created_at=row["created_at"],
                    payload=payload,
                    proposal_id=payload.get("proposal_id"),
                    proposal_version=payload.get("proposal_version"),
                )
            )
        return events
