from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from claim_trellis import __version__
from claim_trellis.accounts import PostgresAccountProfiles
from claim_trellis.audit import run_audit
from claim_trellis.auth import AuthPrincipal, principal
from claim_trellis.config import Settings, get_settings
from claim_trellis.hosted_usage import (
    HostedProviderUnavailable,
    HostedUsageLimit,
    MeteredProvider,
    PostgresUsageGuard,
    requester_ip_hash,
)
from claim_trellis.ingestion import IngestionError, parse_document_bytes
from claim_trellis.models import (
    AuditEvent,
    AuditRequest,
    ClaimAudit,
    EvidenceSearchRequest,
    HumanReviewRequest,
    ParsedDocument,
    ProposalVersion,
    RetrievedCandidate,
    RevisionRequest,
    RevisionRun,
)
from claim_trellis.postgres_store import PostgresAuditStore
from claim_trellis.provider import JudgmentProvider
from claim_trellis.providers import TypeSafeJevProvider
from claim_trellis.retrieval import retrieve
from claim_trellis.revisions import revise
from claim_trellis.storage import AuditStore, LifecycleConflict
from claim_trellis.store import AuditStoreProtocol, SQLiteAsyncStore

Principal = Annotated[AuthPrincipal, Depends(principal)]


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    resolved_settings.validate_runtime()
    resolved_settings.ensure_local_paths()
    if resolved_settings.selected_storage_backend == "postgres":
        assert resolved_settings.database_url is not None
        lifecycle_store: AuditStoreProtocol = PostgresAuditStore(resolved_settings.database_url)
        store: AuditStore | PostgresAuditStore = lifecycle_store  # type: ignore[assignment]
    else:
        store = AuditStore(resolved_settings.resolved_database_path)
        lifecycle_store = SQLiteAsyncStore(legacy_store=store)

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        instance.state.auth_client = httpx.AsyncClient(
            timeout=10, transport=getattr(instance.state, "auth_transport", None)
        )
        if isinstance(store, PostgresAuditStore):
            await store.open()
        try:
            yield
        finally:
            await instance.state.auth_client.aclose()
            if isinstance(store, PostgresAuditStore):
                await store.close()

    app = FastAPI(
        title="ClaimTrellis API",
        version=__version__,
        description="Auditable claim-to-source verification with human final judgment.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.store = store
    app.state.lifecycle_store = lifecycle_store
    app.state.judgment_provider = None
    app.state.usage_guard = (
        PostgresUsageGuard(store.pool) if isinstance(store, PostgresAuditStore) else None
    )
    app.state.account_profiles = (
        PostgresAccountProfiles(store.pool) if isinstance(store, PostgresAuditStore) else None
    )

    def database() -> AuditStoreProtocol:
        return cast(AuditStoreProtocol, app.state.lifecycle_store)

    @app.exception_handler(LifecycleConflict)
    async def lifecycle_conflict(request: Request, exc: LifecycleConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(HostedUsageLimit)
    async def hosted_usage_limit(request: Request, exc: HostedUsageLimit) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content={
                "detail": {"code": "hosted_provider_limit", "scope": exc.scope, "message": str(exc)}
            },
        )

    @app.exception_handler(HostedProviderUnavailable)
    async def hosted_provider_unavailable(
        request: Request, exc: HostedProviderUnavailable
    ) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    def hosted_provider(identity: AuthPrincipal, request: Request) -> MeteredProvider:
        active: Settings = app.state.settings
        if not active.hosted_provider_enabled:
            raise HostedProviderUnavailable("Hosted provider evaluation is not enabled.")
        provider: JudgmentProvider | None = app.state.judgment_provider
        if provider is None and active.judgment_provider == "typesafe_jev" and active.jev_api_key:
            provider = TypeSafeJevProvider(
                api_key=active.jev_api_key,
                endpoint=active.jev_endpoint,
                model=active.jev_model,
                timeout_seconds=active.jev_timeout_seconds,
                max_retries=active.jev_max_retries,
            )
        if (
            provider is None
            or not active.jev_api_key
            or not active.ip_hash_secret
            or app.state.usage_guard is None
        ):
            raise HostedProviderUnavailable("Hosted provider is unavailable.")
        return MeteredProvider(
            provider,
            app.state.usage_guard,
            identity.user_id,
            requester_ip_hash(request, active.ip_hash_secret),
            "audit",
        )

    @app.get("/healthz")
    def health() -> dict[str, object]:
        active = app.state.settings
        return {
            "status": "ok",
            "version": __version__,
            "judgment_provider": active.judgment_provider,
            "provider_configured": bool(active.jev_api_key),
            "hosted_provider_enabled": active.hosted_provider_enabled,
            "hosted_provider_available": bool(
                active.hosted_provider_enabled and active.jev_api_key and active.ip_hash_secret
            ),
            "jev_model": active.jev_model,
            "auto_accept_enabled": False,
            "storage_backend": active.selected_storage_backend,
            "auth_mode": active.auth_mode,
        }

    @app.get("/api/v1/auth/config")
    def auth_config() -> dict[str, str | bool | None]:
        return {
            "enabled": resolved_settings.auth_mode == "supabase",
            "provider": resolved_settings.auth_mode,
            "account_access_enabled": (
                resolved_settings.account_access_enabled
                and resolved_settings.auth_mode == "supabase"
            ),
            "supabase_url": resolved_settings.supabase_url
            if resolved_settings.auth_mode == "supabase"
            else None,
            "publishable_key": (
                resolved_settings.supabase_publishable_key
                if resolved_settings.auth_mode == "supabase"
                else None
            ),
        }

    def account_store(identity: AuthPrincipal) -> PostgresAccountProfiles:
        if not resolved_settings.account_access_enabled or app.state.account_profiles is None:
            raise HTTPException(status_code=503, detail="Account access is not enabled.")
        if identity.is_anonymous:
            raise HTTPException(status_code=403, detail="Link an identity before opening Account.")
        return cast(PostgresAccountProfiles, app.state.account_profiles)

    def account_view(identity: AuthPrincipal, row: dict[str, object] | None) -> dict[str, object]:
        return {
            "user_id": identity.user_id,
            "user_email": identity.email if identity.email_verified else None,
            "email_verified": identity.email_verified,
            "primary_auth_method": identity.primary_auth_method,
            "connected_methods": list(identity.connected_methods),
            "created_at": row["created_at"] if row else None,
            "product_updates_opt_in": row["product_updates_opt_in"] if row else False,
        }

    @app.get("/api/v1/account")
    async def get_account(identity: Principal) -> dict[str, object]:
        row = await account_store(identity).get(identity.user_id)
        return account_view(identity, row)

    @app.post("/api/v1/account/sync")
    async def sync_account(identity: Principal) -> dict[str, object]:
        row = await account_store(identity).sync(identity)
        return account_view(identity, row)

    @app.post("/api/v1/documents/parse", response_model=ParsedDocument)
    async def parse_document(
        document: Annotated[UploadFile, File(...)],
        identity: Principal,
    ) -> ParsedDocument:
        _ = identity
        active: Settings = app.state.settings
        data = await document.read(active.max_upload_bytes + 1)
        try:
            return parse_document_bytes(
                document.filename or "upload.txt",
                data,
                document.content_type or "application/octet-stream",
                max_bytes=active.max_upload_bytes,
                max_chars=active.max_source_chars,
            )
        except IngestionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/v1/evidence/search", response_model=list[RetrievedCandidate])
    def evidence_search(
        request: EvidenceSearchRequest, identity: Principal
    ) -> list[RetrievedCandidate]:
        _ = identity
        return retrieve(request.claim, request.source_text, top_k=request.top_k)

    @app.post("/api/v1/audits", response_model=ClaimAudit, status_code=201)
    async def create_audit(
        request: AuditRequest,
        identity: Principal,
        http_request: Request,
    ) -> ClaimAudit:
        active: Settings = app.state.settings
        if len(request.source_text) > active.max_source_chars:
            raise HTTPException(status_code=413, detail="Source text exceeds the configured limit.")
        provider = app.state.judgment_provider
        if active.auth_mode == "supabase" and request.use_judgment_provider:
            provider = hosted_provider(identity, http_request)
        audit = await run_audit(request, active, judgment_provider=provider)
        return await database().save(identity.user_id, audit)

    @app.get("/api/v1/audits", response_model=list[ClaimAudit])
    async def list_audits(
        identity: Principal, limit: int = 50, offset: int = 0
    ) -> list[ClaimAudit]:
        return await database().list_audits(
            identity.user_id, limit=min(max(limit, 1), 200), offset=max(offset, 0)
        )

    @app.get("/api/v1/audits/{audit_id}", response_model=ClaimAudit)
    async def get_audit(audit_id: str, identity: Principal) -> ClaimAudit:
        audit = await database().get(identity.user_id, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="Audit not found.")
        return audit

    @app.post("/api/v1/audits/{audit_id}/reviews", response_model=ClaimAudit)
    async def review_audit(
        audit_id: str,
        request: HumanReviewRequest,
        identity: Principal,
    ) -> ClaimAudit:
        await get_audit(audit_id, identity)
        return await database().review(identity.user_id, audit_id, request)

    @app.get("/api/v1/audits/{audit_id}/proposals", response_model=list[ProposalVersion])
    async def proposal_history(audit_id: str, identity: Principal) -> list[ProposalVersion]:
        await get_audit(audit_id, identity)
        return await database().proposals(identity.user_id, audit_id)

    @app.get("/api/v1/audits/{audit_id}/proposals/current", response_model=ProposalVersion)
    async def current_proposal(audit_id: str, identity: Principal) -> ProposalVersion:
        return (await proposal_history(audit_id, identity))[-1]

    @app.get("/api/v1/audits/{audit_id}/revisions", response_model=list[RevisionRun])
    async def revision_history(audit_id: str, identity: Principal) -> list[RevisionRun]:
        await get_audit(audit_id, identity)
        return await database().revisions(identity.user_id, audit_id)

    @app.post("/api/v1/audits/{audit_id}/revisions", response_model=RevisionRun)
    async def request_revision(
        audit_id: str, request: RevisionRequest, identity: Principal, http_request: Request
    ) -> RevisionRun:
        await get_audit(audit_id, identity)
        usage_guard = None
        ip_hash = None
        if resolved_settings.auth_mode == "supabase":
            # Perform availability and trusted-IP checks before creating a revision run.
            metered = hosted_provider(identity, http_request)
            usage_guard = metered.guard
            ip_hash = metered.ip_hash
            provider = metered.provider
        else:
            provider = app.state.judgment_provider
        return await revise(
            database(),
            audit_id,
            request,
            resolved_settings,
            provider,
            owner_user_id=identity.user_id,
            usage_guard=usage_guard,
            ip_hash=ip_hash,
        )

    @app.get("/api/v1/audits/{audit_id}/events", response_model=list[AuditEvent])
    async def audit_events(audit_id: str, identity: Principal) -> list[AuditEvent]:
        await get_audit(audit_id, identity)
        return await database().events(identity.user_id, audit_id)

    packaged_web_dir = Path(__file__).resolve().parent / "web"
    source_web_dir = Path(__file__).resolve().parents[2] / "web"
    web_dir = packaged_web_dir if packaged_web_dir.exists() else source_web_dir
    if web_dir.exists():
        app.mount("/assets", StaticFiles(directory=web_dir), name="assets")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        @app.get("/history", include_in_schema=False)
        def history() -> FileResponse:
            return FileResponse(web_dir / "history.html")

    return app


app: FastAPI = create_app()
