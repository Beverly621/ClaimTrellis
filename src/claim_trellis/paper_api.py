"""Additive Paper Workflow routes. No PaperVerdict or ClaimAudit execution endpoint."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, TypeVar, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from claim_trellis.auth import AuthPrincipal, principal
from claim_trellis.paper_models import (
    CandidateCreate,
    ClaimCandidate,
    ClaimSourceLink,
    Contract,
    Manuscript,
    ManuscriptCreate,
    ProjectCreate,
    ReferenceCreate,
    ReferenceEntry,
    ResearchProject,
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
