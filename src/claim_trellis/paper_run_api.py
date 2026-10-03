"""One request plans a run; another executes at most one ordinary ClaimAudit."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request

from claim_trellis.config import Settings
from claim_trellis.hosted_usage import HostedProviderUnavailable, requester_ip_hash
from claim_trellis.paper_api import Principal, checked
from claim_trellis.paper_run_models import (
    AuditItemExecute,
    AuditRunCreate,
    ProjectAuditRun,
    ProjectAuditRunItem,
)
from claim_trellis.paper_runs import PaperRunStore
from claim_trellis.provider import JudgmentProvider
from claim_trellis.providers import TypeSafeJevProvider

router = APIRouter(prefix="/api/v1/projects", tags=["Paper Orchestration"])


def runs(request: Request) -> PaperRunStore:
    return cast(PaperRunStore, request.app.state.paper_run_store)


Store = Annotated[PaperRunStore, Depends(runs)]


def provider_for(request: Request) -> tuple[JudgmentProvider | None, str | None]:
    s: Settings = request.app.state.settings
    provider = request.app.state.judgment_provider
    ip_hash = None
    if s.auth_mode == "supabase":
        if (
            not s.hosted_provider_enabled
            or not s.jev_api_key
            or not s.ip_hash_secret
            or request.app.state.usage_guard is None
        ):
            return None, None
        try:
            ip_hash = requester_ip_hash(request, s.ip_hash_secret)
        except HostedProviderUnavailable:
            return None, None
    if provider is None and s.judgment_provider == "typesafe_jev" and s.jev_api_key:
        provider = TypeSafeJevProvider(
            api_key=s.jev_api_key,
            endpoint=s.jev_endpoint,
            model=s.jev_model,
            timeout_seconds=s.jev_timeout_seconds,
            max_retries=s.jev_max_retries,
        )
    return provider, ip_hash


@router.post("/{project_id}/audit-runs", response_model=ProjectAuditRun, status_code=201)
async def plan(
    project_id: str, body: AuditRunCreate, request: Request, identity: Principal, store: Store
) -> ProjectAuditRun:
    _, ip_hash = provider_for(request)
    return await checked(store.plan(identity.user_id, project_id, body, ip_hash=ip_hash))


@router.get("/{project_id}/audit-runs", response_model=list[ProjectAuditRun])
async def listing(
    project_id: str,
    identity: Principal,
    store: Store,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ProjectAuditRun]:
    return await checked(store.list(identity.user_id, project_id, limit, offset))


@router.get("/{project_id}/audit-runs/{run_id}", response_model=ProjectAuditRun)
async def get(
    project_id: str, run_id: str, request: Request, identity: Principal, store: Store
) -> ProjectAuditRun:
    _, ip_hash = provider_for(request)
    return await checked(store.get(identity.user_id, project_id, run_id, ip_hash=ip_hash))


@router.post(
    "/{project_id}/audit-runs/{run_id}/items/{item_id}/execute", response_model=ProjectAuditRunItem
)
async def execute(
    project_id: str,
    run_id: str,
    item_id: str,
    body: AuditItemExecute,
    request: Request,
    identity: Principal,
    store: Store,
) -> ProjectAuditRunItem:
    provider, ip_hash = provider_for(request)
    return await checked(
        store.execute(identity.user_id, project_id, run_id, item_id, body, provider, ip_hash)
    )
