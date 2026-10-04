"""Additive Paper Workflow routes. No PaperVerdict or ClaimAudit execution endpoint."""

from __future__ import annotations

from collections.abc import Awaitable
from functools import partial
from typing import Annotated, TypeVar, cast

from anyio import to_thread
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from psycopg.errors import UndefinedTable

from claim_trellis.auth import AuthPrincipal, principal
from claim_trellis.config import Settings
from claim_trellis.ingestion import parse_document_bytes
from claim_trellis.paper_models import (
    CandidateCreate,
    CandidateDecision,
    ClaimCandidate,
    ClaimSourceLink,
    Contract,
    Manuscript,
    ManuscriptCreate,
    MappingDecision,
    MappingSuggestions,
    PaperSourceMetadata,
    ProjectCreate,
    ReferenceCreate,
    ReferenceEntry,
    ResearchProject,
    SourceDocument,
    SourceLinkCreate,
    WorkflowEvent,
)
from claim_trellis.paper_store import PaperWorkflowStore, WorkflowNotFound
from claim_trellis.storage import LifecycleConflict

router = APIRouter(prefix="/api/v1/projects", tags=["Paper Workflow"])
Principal = Annotated[AuthPrincipal, Depends(principal)]
T = TypeVar("T")


def workflow(request: Request) -> PaperWorkflowStore:
    return cast(PaperWorkflowStore, request.app.state.paper_workflow_store)


Store = Annotated[PaperWorkflowStore, Depends(workflow)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


async def checked(operation: Awaitable[T]) -> T:
    try:
        return await operation
    except WorkflowNotFound as exc:
        raise HTTPException(status_code=404, detail="Workflow record not found.") from exc
    except UndefinedTable as exc:
        # A successful deployment does not authorize or apply production migrations.
        # Keep P0 available and fail this additive workflow closed without SQL details.
        raise HTTPException(
            status_code=503,
            detail="Paper Workflow is unavailable until an operator applies the required database migrations.",
        ) from exc
    except LifecycleConflict:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=ResearchProject, status_code=201)
async def create_project(
    request: ProjectCreate, identity: Principal, store: Store
) -> ResearchProject:
    return await checked(store.create_project(identity.user_id, request))


@router.get("", response_model=list[ResearchProject])
async def list_projects(
    identity: Principal, store: Store, limit: Limit = 50, offset: Offset = 0
) -> list[ResearchProject]:
    return await checked(store.list_projects(identity.user_id, limit, offset))


@router.get("/{project_id}", response_model=ResearchProject)
async def get_project(project_id: str, identity: Principal, store: Store) -> ResearchProject:
    return await checked(store.get_project(identity.user_id, project_id))


@router.get("/{project_id}/events", response_model=list[WorkflowEvent])
async def events(
    project_id: str, identity: Principal, store: Store, limit: Limit = 200, offset: Offset = 0
) -> list[WorkflowEvent]:
    return await checked(store.events(identity.user_id, project_id, limit, offset))


@router.post("/{project_id}/manuscripts", response_model=Manuscript, status_code=201)
async def create_manuscript(
    project_id: str, request: ManuscriptCreate, identity: Principal, store: Store
) -> Manuscript:
    return await checked(store.create_manuscript(identity.user_id, project_id, request))


@router.get("/{project_id}/manuscripts", response_model=list[Manuscript])
async def manuscripts(
    project_id: str, identity: Principal, store: Store, limit: Limit = 50, offset: Offset = 0
) -> list[Contract]:
    return await checked(
        store.list_records(identity.user_id, project_id, "manuscript", limit=limit, offset=offset)
    )


@router.get("/{project_id}/manuscripts/{manuscript_id}", response_model=Manuscript)
async def manuscript(
    project_id: str, manuscript_id: str, identity: Principal, store: Store
) -> Contract:
    return await checked(store.get(identity.user_id, project_id, manuscript_id, "manuscript"))


@router.post(
    "/{project_id}/manuscripts/{manuscript_id}/candidates",
    response_model=ClaimCandidate,
    status_code=201,
)
async def create_candidate(
    project_id: str, manuscript_id: str, request: CandidateCreate, identity: Principal, store: Store
) -> ClaimCandidate:
    return await checked(
        store.create_candidate(identity.user_id, project_id, manuscript_id, request)
    )


@router.get(
    "/{project_id}/manuscripts/{manuscript_id}/candidates", response_model=list[ClaimCandidate]
)
async def candidates(
    project_id: str,
    manuscript_id: str,
    identity: Principal,
    store: Store,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[Contract]:
    await checked(store.get(identity.user_id, project_id, manuscript_id, "manuscript"))
    return await checked(
        store.list_records(identity.user_id, project_id, "candidate", manuscript_id, limit, offset)
    )


@router.get("/{project_id}/candidates/{candidate_id}", response_model=ClaimCandidate)
async def candidate(
    project_id: str, candidate_id: str, identity: Principal, store: Store
) -> Contract:
    return await checked(store.get(identity.user_id, project_id, candidate_id, "candidate"))


@router.post(
    "/{project_id}/manuscripts/{manuscript_id}/extract-candidates",
    response_model=list[ClaimCandidate],
)
async def extract_candidates(
    project_id: str, manuscript_id: str, identity: Principal, store: Store
) -> list[Contract]:
    return await checked(store.extract_candidates(identity.user_id, project_id, manuscript_id))


@router.post("/{project_id}/candidates/{candidate_id}/decisions", response_model=ClaimCandidate)
async def decide_candidate(
    project_id: str,
    candidate_id: str,
    request: CandidateDecision,
    identity: Principal,
    store: Store,
) -> ClaimCandidate:
    return await checked(
        store.decide_candidate(identity.user_id, project_id, candidate_id, request)
    )


@router.post(
    "/{project_id}/manuscripts/{manuscript_id}/references",
    response_model=ReferenceEntry,
    status_code=201,
)
async def create_reference(
    project_id: str, manuscript_id: str, request: ReferenceCreate, identity: Principal, store: Store
) -> ReferenceEntry:
    return await checked(
        store.create_reference(identity.user_id, project_id, manuscript_id, request)
    )


@router.get(
    "/{project_id}/manuscripts/{manuscript_id}/references", response_model=list[ReferenceEntry]
)
async def references(
    project_id: str,
    manuscript_id: str,
    identity: Principal,
    store: Store,
    limit: Limit = 50,
    offset: Offset = 0,
) -> list[Contract]:
    await checked(store.get(identity.user_id, project_id, manuscript_id, "manuscript"))
    return await checked(
        store.list_records(identity.user_id, project_id, "reference", manuscript_id, limit, offset)
    )


@router.get("/{project_id}/references/{reference_id}", response_model=ReferenceEntry)
async def reference(
    project_id: str, reference_id: str, identity: Principal, store: Store
) -> Contract:
    return await checked(store.get(identity.user_id, project_id, reference_id, "reference"))


@router.post("/{project_id}/source-links", response_model=ClaimSourceLink, status_code=201)
async def create_source_link(
    project_id: str, request: SourceLinkCreate, identity: Principal, store: Store
) -> ClaimSourceLink:
    return await checked(store.create_source_link(identity.user_id, project_id, request))


@router.get("/{project_id}/source-links", response_model=list[ClaimSourceLink])
async def source_links(
    project_id: str, identity: Principal, store: Store, limit: Limit = 50, offset: Offset = 0
) -> list[Contract]:
    return await checked(
        store.list_records(identity.user_id, project_id, "source_link", limit=limit, offset=offset)
    )


@router.get("/{project_id}/source-links/{link_id}", response_model=ClaimSourceLink)
async def source_link(project_id: str, link_id: str, identity: Principal, store: Store) -> Contract:
    return await checked(store.get(identity.user_id, project_id, link_id, "source_link"))


@router.post(
    "/{project_id}/manuscripts/{manuscript_id}/parse-references",
    response_model=list[ReferenceEntry],
)
async def parse_references(
    project_id: str, manuscript_id: str, identity: Principal, store: Store
) -> list[Contract]:
    return await checked(store.parse_references(identity.user_id, project_id, manuscript_id))


@router.post("/{project_id}/sources", response_model=SourceDocument, status_code=201)
async def upload_source(
    project_id: str,
    identity: Principal,
    store: Store,
    http_request: Request,
    document: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Form(min_length=8, max_length=200)],
    metadata: Annotated[str, Form(max_length=16_000)] = "{}",
) -> SourceDocument:
    await checked(store.get_project(identity.user_id, project_id))
    settings: Settings = http_request.app.state.settings
    try:
        source_metadata = PaperSourceMetadata.model_validate_json(metadata)
        data = await document.read(settings.max_upload_bytes + 1)
        parsed = await to_thread.run_sync(
            partial(
                parse_document_bytes,
                document.filename or "upload.txt",
                data,
                document.content_type or "application/octet-stream",
                max_bytes=settings.max_upload_bytes,
                max_chars=settings.max_source_chars,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid source document or metadata.") from exc
    finally:
        await document.close()
    return await checked(
        store.create_source(identity.user_id, project_id, idempotency_key, parsed, source_metadata)
    )


@router.get("/{project_id}/sources", response_model=list[SourceDocument])
async def sources(
    project_id: str, identity: Principal, store: Store, limit: Limit = 50, offset: Offset = 0
) -> list[Contract]:
    return await checked(
        store.list_records(
            identity.user_id, project_id, "source_document", limit=limit, offset=offset
        )
    )


@router.get("/{project_id}/sources/{source_id}", response_model=SourceDocument)
async def source(project_id: str, source_id: str, identity: Principal, store: Store) -> Contract:
    return await checked(store.get(identity.user_id, project_id, source_id, "source_document"))


@router.post(
    "/{project_id}/candidates/{candidate_id}/suggest-mappings", response_model=MappingSuggestions
)
async def suggest_mappings(
    project_id: str, candidate_id: str, identity: Principal, store: Store
) -> MappingSuggestions:
    return await checked(store.suggest_mappings(identity.user_id, project_id, candidate_id))


@router.post("/{project_id}/source-links/{link_id}/decisions", response_model=ClaimSourceLink)
async def decide_mapping(
    project_id: str, link_id: str, request: MappingDecision, identity: Principal, store: Store
) -> ClaimSourceLink:
    return await checked(store.decide_mapping(identity.user_id, project_id, link_id, request))
