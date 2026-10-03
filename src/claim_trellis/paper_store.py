"""Transactional owner-scoped Paper Workflow records; no provider or audit execution."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from anyio import to_thread
from psycopg.types.json import Jsonb

from claim_trellis.citations import citation_markers
from claim_trellis.document_blocks import text_blocks, validate_blocks
from claim_trellis.models import utc_now
from claim_trellis.paper_models import (
    ID_FIELDS,
    RECORD_MODELS,
    CandidateCreate,
    CandidateDecision,
    ClaimCandidate,
    ClaimSourceLink,
    Contract,
    Manuscript,
    ManuscriptCreate,
    ProjectAuditLink,
    ProjectCreate,
    ReferenceCreate,
    ReferenceEntry,
    ResearchProject,
    SourceLinkCreate,
    WorkflowEvent,
    WorkflowRecord,
)
from claim_trellis.storage import LifecycleConflict
from claim_trellis.store import LOCAL_USER_ID


class WorkflowNotFound(LookupError):
    pass


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def stable_id(scope: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"claim-trellis:paper-workflow:{scope}:{key}"))


class _Connection:
    def __init__(self, connection: Any, postgres: bool) -> None:
        self.raw, self.postgres = connection, postgres

    async def execute(self, query: str, args: Sequence[object] = ()) -> list[dict[str, Any]]:
        if self.postgres:
            parameters = tuple(Jsonb(value) if isinstance(value, dict) else value for value in args)
            cursor = await self.raw.execute(query.replace("?", "%s"), parameters)
            return list(await cursor.fetchall()) if cursor.description else []

        def run() -> list[dict[str, Any]]:
            parameters = tuple(
                json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value
                for value in args
            )
            cursor = self.raw.execute(query, parameters)
            return [dict(row) for row in cursor.fetchall()] if cursor.description else []

        return await to_thread.run_sync(run)


def _decode(row: dict[str, Any], model: type[Contract], field: str = "record_json") -> Contract:
    value = row[field]
    return (
        model.model_validate_json(value) if isinstance(value, str) else model.model_validate(value)
    )


class PaperWorkflowStore:
    """Shared domain logic with SQLite/threadpool and existing PostgreSQL pool adapters."""

    def __init__(self, *, path: Path | None = None, pool: Any = None) -> None:
        if (path is None) == (pool is None):
            raise ValueError("Provide exactly one SQLite path or PostgreSQL pool.")
        self.path, self.pool = path, pool
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE IF NOT EXISTS research_projects (
                        project_id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL,
                        creation_sha256 TEXT NOT NULL, record_json TEXT NOT NULL,
                        created_at TEXT NOT NULL, UNIQUE(project_id,owner_user_id));
                    CREATE TABLE IF NOT EXISTS paper_workflow_records (
                        record_id TEXT PRIMARY KEY, project_id TEXT NOT NULL,
                        owner_user_id TEXT NOT NULL, kind TEXT NOT NULL, parent_id TEXT,
                        creation_sha256 TEXT NOT NULL, record_json TEXT NOT NULL, created_at TEXT NOT NULL,
                        UNIQUE(record_id,project_id,owner_user_id),
                        FOREIGN KEY(project_id,owner_user_id) REFERENCES research_projects(project_id,owner_user_id),
                        FOREIGN KEY(parent_id,project_id,owner_user_id)
                            REFERENCES paper_workflow_records(record_id,project_id,owner_user_id));
                    CREATE INDEX IF NOT EXISTS idx_workflow_project_kind ON paper_workflow_records
                        (project_id,owner_user_id,kind,created_at,record_id);
                    CREATE TABLE IF NOT EXISTS paper_workflow_events (
                        event_seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                        project_id TEXT NOT NULL, owner_user_id TEXT NOT NULL, record_id TEXT,
                        event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                        FOREIGN KEY(project_id,owner_user_id) REFERENCES research_projects(project_id,owner_user_id));
                """)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[_Connection]:
        if self.pool is not None:
            async with self.pool.connection() as raw, raw.transaction():
                yield _Connection(raw, True)
        else:
            assert self.path is not None
            sqlite_path = self.path
            raw = await to_thread.run_sync(
                lambda: sqlite3.connect(sqlite_path, timeout=15, check_same_thread=False)
            )
            raw.row_factory = sqlite3.Row
            connection = _Connection(raw, False)
            try:
                await connection.execute("PRAGMA foreign_keys=ON")
                await connection.execute("BEGIN IMMEDIATE")
                yield connection
                await to_thread.run_sync(raw.commit)
            except BaseException:
                await to_thread.run_sync(raw.rollback)
                raise
            finally:
                await to_thread.run_sync(raw.close)

    async def _project(self, conn: _Connection, owner: str, project: str) -> ResearchProject:
        rows = await conn.execute(
            "SELECT record_json FROM research_projects WHERE project_id=? AND owner_user_id=?"
            + (" FOR UPDATE" if conn.postgres else ""),
            (project, owner),
        )
        if not rows:
            raise WorkflowNotFound("Project not found.")
        return cast(ResearchProject, _decode(rows[0], ResearchProject))

    async def _record(
        self, conn: _Connection, owner: str, project: str, record_id: str, kind: str
    ) -> Contract:
        rows = await conn.execute(
            "SELECT record_json FROM paper_workflow_records WHERE record_id=? AND project_id=? AND owner_user_id=? AND kind=?",
            (record_id, project, owner, kind),
        )
        if not rows:
            raise WorkflowNotFound("Workflow record not found.")
        return _decode(rows[0], RECORD_MODELS[kind])

    async def _event(
        self,
        conn: _Connection,
        owner: str,
        project: str,
        kind: str,
        payload: dict[str, object],
        record_id: str | None = None,
        event_id: str | None = None,
    ) -> None:
        await conn.execute(
            "INSERT INTO paper_workflow_events(event_id,project_id,owner_user_id,record_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                event_id or str(uuid4()),
                project,
                owner,
                record_id,
                kind,
                payload,
                utc_now().isoformat(),
            ),
        )

    async def create_project(self, owner: str, request: ProjectCreate) -> ResearchProject:
        project = ResearchProject(
            project_id=stable_id(owner, "project:" + request.idempotency_key),
            name=request.name,
            description=request.description,
        )
        fingerprint = digest(request.model_dump(mode="json"))
        async with self.transaction() as conn:
            rows = await conn.execute(
                "SELECT creation_sha256,record_json FROM research_projects WHERE project_id=? AND owner_user_id=?",
                (project.project_id, owner),
            )
            if rows:
                if rows[0]["creation_sha256"] != fingerprint:
                    raise LifecycleConflict(
                        "Idempotency key already used for different project content."
                    )
                return cast(ResearchProject, _decode(rows[0], ResearchProject))
            await conn.execute(
                "INSERT INTO research_projects(project_id,owner_user_id,creation_sha256,record_json,created_at) VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO NOTHING",
                (
                    project.project_id,
                    owner,
                    fingerprint,
                    project.model_dump(mode="json"),
                    project.created_at.isoformat(),
                ),
            )
            stored = await self._project(conn, owner, project.project_id)
            rows = await conn.execute(
                "SELECT creation_sha256 FROM research_projects WHERE project_id=? AND owner_user_id=?",
                (project.project_id, owner),
            )
            if rows[0]["creation_sha256"] != fingerprint:
                raise LifecycleConflict(
                    "Idempotency key already used for different project content."
                )
            # A deterministic creation event prevents duplicate events under concurrent replay.
            event_id = stable_id(project.project_id, "project.created")
            await conn.execute(
                "INSERT INTO paper_workflow_events(event_id,project_id,owner_user_id,record_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(event_id) DO NOTHING",
                (
                    event_id,
                    project.project_id,
                    owner,
                    None,
                    "project.created",
                    {"project_id": project.project_id},
                    project.created_at.isoformat(),
                ),
            )
            return stored

    async def get_project(self, owner: str, project: str) -> ResearchProject:
        async with self.transaction() as conn:
            return await self._project(conn, owner, project)

    async def list_projects(
        self, owner: str, limit: int = 50, offset: int = 0
    ) -> list[ResearchProject]:
        async with self.transaction() as conn:
            rows = await conn.execute(
                "SELECT record_json FROM research_projects WHERE owner_user_id=? ORDER BY created_at,project_id LIMIT ? OFFSET ?",
                (owner, min(max(limit, 1), 200), max(offset, 0)),
            )
            return [cast(ResearchProject, _decode(row, ResearchProject)) for row in rows]

    async def get(self, owner: str, project: str, record_id: str, kind: str) -> Contract:
        async with self.transaction() as conn:
            await self._project(conn, owner, project)
            return await self._record(conn, owner, project, record_id, kind)

    async def list_records(
        self,
        owner: str,
        project: str,
        kind: str,
        parent_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Contract]:
        async with self.transaction() as conn:
            await self._project(conn, owner, project)
            query = "SELECT record_json FROM paper_workflow_records WHERE project_id=? AND owner_user_id=? AND kind=?"
            args: list[object] = [project, owner, kind]
            if parent_id is not None:
                query += " AND parent_id=?"
                args.append(parent_id)
            rows = await conn.execute(
                query + " ORDER BY created_at,record_id LIMIT ? OFFSET ?",
                [*args, min(max(limit, 1), 200), max(offset, 0)],
            )
            return [_decode(row, RECORD_MODELS[kind]) for row in rows]

    async def events(
        self, owner: str, project: str, limit: int = 200, offset: int = 0
    ) -> list[WorkflowEvent]:
        async with self.transaction() as conn:
            await self._project(conn, owner, project)
            rows = await conn.execute(
                "SELECT event_id,project_id,record_id,event_type,payload_json,created_at FROM paper_workflow_events WHERE project_id=? AND owner_user_id=? ORDER BY event_seq LIMIT ? OFFSET ?",
                (project, owner, min(max(limit, 1), 500), max(offset, 0)),
            )
            return [
                WorkflowEvent(
                    event_id=row["event_id"],
                    project_id=project,
                    record_id=row["record_id"],
                    event_type=row["event_type"],
                    payload=json.loads(row["payload_json"])
                    if isinstance(row["payload_json"], str)
                    else row["payload_json"],
                    created_at=row["created_at"],
                )
                for row in rows
            ]

    async def _insert(
        self, conn: _Connection, owner: str, kind: str, record: WorkflowRecord, parent: str | None
    ) -> Contract:
        project = str(record.project_id)
        record_id = str(getattr(record, ID_FIELDS[kind]))
        fingerprint = digest(record.model_dump(mode="json", exclude={"created_at"}))
        rows = await conn.execute(
            "SELECT creation_sha256,record_json FROM paper_workflow_records WHERE record_id=? AND project_id=? AND owner_user_id=? AND kind=?",
            (record_id, project, owner, kind),
        )
        if rows:
            if rows[0]["creation_sha256"] != fingerprint:
                raise LifecycleConflict(
                    "Idempotency key already used for different workflow content."
                )
            return _decode(rows[0], RECORD_MODELS[kind])
        await conn.execute(
            "INSERT INTO paper_workflow_records(record_id,project_id,owner_user_id,kind,parent_id,creation_sha256,record_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                record_id,
                project,
                owner,
                kind,
                parent,
                fingerprint,
                record.model_dump(mode="json"),
                str(record.created_at.isoformat()),
            ),
        )
        await self._event(
            conn,
            owner,
            project,
            kind + ".created",
            {
                "record_id": record_id,
                "sha256": str(getattr(record, "sha256", getattr(record, "content_sha256", ""))),
            },
            record_id,
        )
        return record

    async def _validate_record(
        self, conn: _Connection, owner: str, kind: str, record: WorkflowRecord
    ) -> str | None:
        project = str(record.project_id)
        if isinstance(record, Manuscript):
            validate_blocks(record.text, record.blocks)
            if hashlib.sha256(record.text.encode()).hexdigest() != record.content_sha256:
                raise ValueError("Manuscript hash does not match its text.")
            return None
        if isinstance(record, (ClaimCandidate, ReferenceEntry)):
            manuscript = cast(
                Manuscript,
                await self._record(conn, owner, project, record.manuscript_id, "manuscript"),
            )
            if isinstance(record, ClaimCandidate):
                start, end = record.exact_span_start, record.exact_span_end
                sentence = manuscript.text[record.sentence_span.start : record.sentence_span.end]
                if (
                    record.sentence_span.end > len(manuscript.text)
                    or sentence != record.source_sentence
                    or manuscript.text[start:end] != record.original_span
                    or hashlib.sha256(record.original_span.encode()).hexdigest() != record.sha256
                ):
                    raise ValueError("Candidate must preserve exact manuscript spans and hash.")
                if any(
                    marker not in citation_markers(sentence) for marker in record.citation_markers
                ):
                    raise ValueError("Candidate citation markers must occur in its sentence.")
            elif (
                record.span.end > len(manuscript.text)
                or manuscript.text[record.span.start : record.span.end] != record.raw_reference
                or hashlib.sha256(record.raw_reference.encode()).hexdigest() != record.sha256
            ):
                raise ValueError("Reference must preserve its exact manuscript span and hash.")
            return record.manuscript_id
        if isinstance(record, ClaimSourceLink):
            candidate = cast(
                ClaimCandidate,
                await self._record(conn, owner, project, record.candidate_id, "candidate"),
            )
            reference = cast(
                ReferenceEntry,
                await self._record(conn, owner, project, record.reference_id, "reference"),
            )
            if candidate.manuscript_id != reference.manuscript_id:
                raise LifecycleConflict(
                    "Candidate and reference must belong to the same manuscript."
                )
            if record.source_document_id is not None:
                await self._record(
                    conn, owner, project, record.source_document_id, "source_document"
                )
            return record.candidate_id
        if isinstance(record, ProjectAuditLink):
            await self._record(conn, owner, project, record.claim_source_link_id, "source_link")
            query = "SELECT audit_id FROM audits WHERE audit_id=?"
            args: list[object] = [record.audit_id]
            if conn.postgres:
                query += " AND owner_user_id=?"
                args.append(owner)
            elif owner != LOCAL_USER_ID:
                raise WorkflowNotFound("Owned audit not found.")
            if not await conn.execute(query, args):
                raise WorkflowNotFound("Owned audit not found.")
            return record.claim_source_link_id
        raise ValueError("Unsupported workflow contract.")

    async def create_records(
        self, owner: str, project: str, kind: str, records: Sequence[WorkflowRecord]
    ) -> list[Contract]:
        async with self.transaction() as conn:
            await self._project(conn, owner, project)
            result = []
            for record in records:
                if record.project_id != project or not isinstance(record, RECORD_MODELS[kind]):
                    raise ValueError("Record kind and project must match the target.")
                parent = await self._validate_record(conn, owner, kind, record)
                result.append(await self._insert(conn, owner, kind, record, parent))
            return result

    async def create_manuscript(
        self, owner: str, project: str, request: ManuscriptCreate
    ) -> Manuscript:
        record = Manuscript(
            manuscript_id=stable_id(project, "manuscript:" + request.idempotency_key),
            project_id=project,
            filename=request.filename,
            media_type=request.media_type,
            text=request.text,
            content_sha256=hashlib.sha256(request.text.encode()).hexdigest(),
            blocks=request.blocks or text_blocks(request.text),
            parser_version=request.parser_version,
        )
        return cast(
            Manuscript, (await self.create_records(owner, project, "manuscript", [record]))[0]
        )

    async def create_candidate(
        self, owner: str, project: str, manuscript_id: str, request: CandidateCreate
    ) -> ClaimCandidate:
        manuscript = cast(Manuscript, await self.get(owner, project, manuscript_id, "manuscript"))
        span = request.clause_span
        original = manuscript.text[span.start : span.end]
        record = ClaimCandidate(
            candidate_id=stable_id(manuscript_id, "candidate:" + request.idempotency_key),
            project_id=project,
            manuscript_id=manuscript_id,
            source_sentence=manuscript.text[
                request.sentence_span.start : request.sentence_span.end
            ],
            sentence_span=request.sentence_span,
            exact_span_start=span.start,
            exact_span_end=span.end,
            original_span=original,
            citation_markers=request.citation_markers,
            suggested_clause_span=span,
            extraction_version="manual-span-v1",
            sha256=hashlib.sha256(original.encode()).hexdigest(),
        )
        return cast(
            ClaimCandidate, (await self.create_records(owner, project, "candidate", [record]))[0]
        )

    async def extract_candidates(
        self, owner: str, project: str, manuscript_id: str
    ) -> list[Contract]:
        from claim_trellis.paper_extraction import extract_candidates

        manuscript = cast(Manuscript, await self.get(owner, project, manuscript_id, "manuscript"))
        return await self.create_records(
            owner, project, "candidate", extract_candidates(manuscript)
        )

    async def _decision_replay(
        self, conn: _Connection, owner: str, project: str, event_id: str, fingerprint: str
    ) -> bool:
        rows = await conn.execute(
            "SELECT payload_json FROM paper_workflow_events WHERE event_id=? AND project_id=? AND owner_user_id=?",
            (event_id, project, owner),
        )
        if not rows:
            return False
        payload = rows[0]["payload_json"]
        payload = json.loads(payload) if isinstance(payload, str) else payload
        if payload["request_sha256"] != fingerprint:
            raise LifecycleConflict("Decision key already used for different content.")
        return True

    async def decide_candidate(
        self, owner: str, project: str, candidate_id: str, request: CandidateDecision
    ) -> ClaimCandidate:
        async with self.transaction() as conn:
            await self._project(conn, owner, project)
            candidate = cast(
                ClaimCandidate, await self._record(conn, owner, project, candidate_id, "candidate")
            )
            event_id = stable_id(candidate_id, "decision:" + request.idempotency_key)
            fingerprint = digest(request.model_dump(mode="json"))
            if await self._decision_replay(conn, owner, project, event_id, fingerprint):
                return candidate
            if (
                candidate.status != "pending"
                or candidate.state_revision != request.expected_state_revision
            ):
                raise LifecycleConflict("Candidate is finalized or the review state is stale.")
            updated = ClaimCandidate.model_validate(
                {
                    **candidate.model_dump(),
                    "status": "rejected" if request.decision == "reject" else "confirmed",
                    "confirmed_claim": None
                    if request.decision == "reject"
                    else request.confirmed_claim or candidate.original_span,
                    "state_revision": candidate.state_revision + 1,
                }
            )
            await conn.execute(
                "UPDATE paper_workflow_records SET record_json=? WHERE record_id=? AND project_id=? AND owner_user_id=? AND kind='candidate'",
                (updated.model_dump(mode="json"), candidate_id, project, owner),
            )
            await self._event(
                conn,
                owner,
                project,
                "candidate." + updated.status,
                {
                    "request_sha256": fingerprint,
                    "request": request.model_dump(mode="json"),
                    "original_span": candidate.original_span,
                    "confirmed_claim": updated.confirmed_claim,
                    "state_revision": updated.state_revision,
                },
                candidate_id,
                event_id,
            )
            return updated

    async def create_reference(
        self, owner: str, project: str, manuscript_id: str, request: ReferenceCreate
    ) -> ReferenceEntry:
        manuscript = cast(Manuscript, await self.get(owner, project, manuscript_id, "manuscript"))
        original = manuscript.text[request.span.start : request.span.end]
        record = ReferenceEntry(
            reference_id=stable_id(manuscript_id, "reference:" + request.idempotency_key),
            project_id=project,
            manuscript_id=manuscript_id,
            manuscript_locator=f"chars:{request.span.start}-{request.span.end}",
            span=request.span,
            raw_reference=original,
            markers=request.markers,
            title=request.title,
            authors=request.authors,
            year=request.year,
            doi=request.doi,
            sha256=hashlib.sha256(original.encode()).hexdigest(),
        )
        return cast(
            ReferenceEntry, (await self.create_records(owner, project, "reference", [record]))[0]
        )

    async def create_source_link(
        self, owner: str, project: str, request: SourceLinkCreate
    ) -> ClaimSourceLink:
        record = ClaimSourceLink(
            link_id=stable_id(project, "source_link:" + request.idempotency_key),
            project_id=project,
            candidate_id=request.candidate_id,
            reference_id=request.reference_id,
        )
        return cast(
            ClaimSourceLink, (await self.create_records(owner, project, "source_link", [record]))[0]
        )
