"""Hosted quota contract: all concurrency assertions use real PostgreSQL."""

import asyncio
import hashlib
import hmac
import ipaddress
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from test_revisions import RevisionProvider

from claim_trellis import api as api_module
from claim_trellis.api import create_app
from claim_trellis.config import Settings
from claim_trellis.hosted_usage import (
    HostedProviderUnavailable,
    HostedUsageLimit,
    MeteredProvider,
    PostgresUsageGuard,
    requester_ip_hash,
)
from claim_trellis.postgres_store import PostgresAuditStore
from claim_trellis.provider import ProviderError

pytest_plugins = ["test_postgres_store"]


def test_ip_hmac_canonicalizes_and_rejects_untrusted_chains(monkeypatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    secret = "test-secret-not-for-production"
    raw_ip = "2001:db8::1"
    request = Request({"type": "http", "headers": [(b"x-forwarded-for", raw_ip.encode())]})
    result = requester_ip_hash(request, secret)
    assert (
        result
        == hmac.new(
            secret.encode(), bytes.fromhex("20010db8000000000000000000000001"), hashlib.sha256
        ).hexdigest()
    )
    assert raw_ip not in result
    bad = Request({"type": "http", "headers": [(b"x-forwarded-for", b"1.2.3.4, 5.6.7.8")]})
    with pytest.raises(HostedProviderUnavailable):
        requester_ip_hash(bad, secret)
    missing = Request({"type": "http", "headers": []})
    with pytest.raises(HostedProviderUnavailable):
        requester_ip_hash(missing, secret)
    monkeypatch.delenv("VERCEL")
    assert requester_ip_hash(request, secret) == requester_ip_hash(bad, secret)


async def opened(url: str) -> PostgresAuditStore:
    store = PostgresAuditStore(url, sslmode="disable")
    await store.open()
    return store


@pytest.mark.asyncio
async def test_user_and_ip_rolling_limits(pg_url: str) -> None:
    store = await opened(pg_url)
    guard = PostgresUsageGuard(store.pool)
    try:
        owner, ip_hash = str(uuid4()), uuid4().hex
        for _ in range(7):
            usage = await guard.reserve(owner, ip_hash, "test", "audit")
            await guard.finish(usage)
        with pytest.raises(HostedUsageLimit) as exceeded:
            await guard.reserve(owner, ip_hash, "test", "audit")
        assert exceeded.value.scope == "user"

        shared_ip = uuid4().hex
        for _ in range(10):
            usage = await guard.reserve(str(uuid4()), shared_ip, "test", "audit")
            await guard.finish(usage)
        with pytest.raises(HostedUsageLimit) as exceeded:
            await guard.reserve(str(uuid4()), shared_ip, "test", "audit")
        assert exceeded.value.scope == "ip"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_revision_cap_and_sanitized_usage_rows(pg_url: str) -> None:
    store = await opened(pg_url)
    guard = PostgresUsageGuard(store.pool)
    owner, ip_hash, audit_id = str(uuid4()), uuid4().hex, str(uuid4())
    try:
        for _ in range(5):
            usage = await guard.reserve(owner, ip_hash, "test", "revision", audit_id=audit_id)
            await guard.finish(usage, error_code="provider_error")
        with pytest.raises(HostedUsageLimit) as exceeded:
            await guard.reserve(owner, ip_hash, "test", "revision", audit_id=audit_id)
        assert exceeded.value.scope == "audit_revision"
        async with store.pool.connection() as conn:
            result = await conn.execute(
                "SELECT ip_hash,error_code,input_tokens,output_tokens FROM provider_usage "
                "WHERE audit_id=%s",
                (audit_id,),
            )
            rows = await result.fetchall()
        assert len(rows) == 5
        assert all(
            row["ip_hash"] == ip_hash and row["error_code"] == "provider_error" for row in rows
        )
        assert all(row["input_tokens"] is None and row["output_tokens"] is None for row in rows)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_concurrent_last_slot_commits_before_provider_call(pg_url: str) -> None:
    first, second = await opened(pg_url), await opened(pg_url)
    owner, ip_hash = str(uuid4()), uuid4().hex
    left, right = PostgresUsageGuard(first.pool), PostgresUsageGuard(second.pool)
    try:
        for _ in range(6):
            await left.reserve(owner, ip_hash, "test", "audit")
        results = await asyncio.gather(
            left.reserve(owner, ip_hash, "test", "audit"),
            right.reserve(owner, ip_hash, "test", "audit"),
            return_exceptions=True,
        )
        assert sum(isinstance(item, str) for item in results) == 1
        assert sum(isinstance(item, HostedUsageLimit) for item in results) == 1

        class SlowProvider(RevisionProvider):
            async def evaluate(self, *args, **kwargs):
                entered.set()
                await release.wait()
                return await super().evaluate(*args, **kwargs)

        entered, release = asyncio.Event(), asyncio.Event()
        probe_owner, probe_ip = str(uuid4()), uuid4().hex
        provider = MeteredProvider(SlowProvider(), left, probe_owner, probe_ip, "audit")
        task = asyncio.create_task(provider.evaluate("Distinct claim", "Distinct evidence"))
        await asyncio.wait_for(entered.wait(), 5)
        async with second.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT status FROM provider_usage WHERE owner_user_id=%s", (probe_owner,)
                )
            ).fetchone()
        assert row["status"] == "started"
        release.set()
        await task
        async with second.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT status,input_tokens,output_tokens FROM provider_usage "
                    "WHERE owner_user_id=%s",
                    (probe_owner,),
                )
            ).fetchone()
        assert row["status"] == "succeeded"
        assert row["input_tokens"] is not None and row["output_tokens"] is not None
    finally:
        await first.close()
        await second.close()


def hosted_settings(pg_url: str, *, enabled: bool = True, key: str | None = "fake-key") -> Settings:
    return Settings(
        database_url=pg_url,
        auth_mode="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        jev_api_key=key,
        hosted_provider_enabled=enabled,
        ip_hash_secret="test-secret-not-for-production",
    )


@pytest.fixture
def local_pg_api(monkeypatch) -> None:
    class LocalPostgresAuditStore(PostgresAuditStore):
        def __init__(self, database_url: str) -> None:
            super().__init__(database_url, sslmode="disable")

    monkeypatch.setattr(api_module, "PostgresAuditStore", LocalPostgresAuditStore)


def install_auth_mock(app) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        try:
            owner = str(UUID(token))
        except ValueError:
            return httpx.Response(401)
        return httpx.Response(200, json={"id": owner, "is_anonymous": True})

    app.state.auth_transport = httpx.MockTransport(handler)


def audit_body(*, provider: bool = True) -> dict[str, object]:
    return {
        "claim": "The method improved retrieval accuracy.",
        "source_text": "The method improved retrieval accuracy on the secondary task.",
        "source": {"access_tier": "excerpt"},
        "use_judgment_provider": provider,
    }


def test_hosted_disabled_missing_key_and_deterministic_path(
    pg_url: str, local_pg_api: None
) -> None:
    owner = str(uuid4())
    headers = {"Authorization": f"Bearer {owner}"}
    app = create_app(hosted_settings(pg_url, enabled=False))
    install_auth_mock(app)
    with TestClient(app) as client:
        health = client.get("/healthz").json()
        assert health["hosted_provider_enabled"] is False
        assert health["hosted_provider_available"] is False
        assert "test-secret" not in str(health)
        denied = client.post("/api/v1/audits", json=audit_body(), headers=headers)
        assert denied.status_code == 503
        assert denied.json()["detail"] == "Hosted provider evaluation is not enabled."
        deterministic = client.post(
            "/api/v1/audits", json=audit_body(provider=False), headers=headers
        )
        assert deterministic.status_code == 201

    missing = create_app(hosted_settings(pg_url, key=None))
    install_auth_mock(missing)
    with TestClient(missing) as client:
        response = client.post("/api/v1/audits", json=audit_body(), headers=headers)
        assert response.status_code == 503
        assert response.json()["detail"] == "Hosted provider is unavailable."

    no_secret = create_app(hosted_settings(pg_url).model_copy(update={"ip_hash_secret": None}))
    install_auth_mock(no_secret)
    with TestClient(no_secret) as client:
        response = client.post("/api/v1/audits", json=audit_body(), headers=headers)
        assert response.status_code == 503
        assert client.get("/healthz").json()["hosted_provider_available"] is False


def test_hosted_audit_user_limit_and_429_shape(
    pg_url: str, local_pg_api: None, monkeypatch
) -> None:
    monkeypatch.setenv("VERCEL", "1")
    app = create_app(hosted_settings(pg_url))
    provider = RevisionProvider()
    app.state.judgment_provider = provider
    install_auth_mock(app)
    owner = str(uuid4())
    headers = {
        "Authorization": f"Bearer {owner}",
        "x-forwarded-for": str(ipaddress.IPv4Address(uuid4().int & 0xFFFFFFFF)),
    }
    with TestClient(app) as client:
        without_ip = client.post(
            "/api/v1/audits", json=audit_body(), headers={"Authorization": f"Bearer {owner}"}
        )
        assert without_ip.status_code == 503
        for _ in range(7):
            assert (
                client.post("/api/v1/audits", json=audit_body(), headers=headers).status_code == 201
            )
        blocked = client.post("/api/v1/audits", json=audit_body(), headers=headers)
        assert blocked.status_code == 429
        assert blocked.json() == {
            "detail": {
                "code": "hosted_provider_limit",
                "scope": "user",
                "message": "Hosted provider usage limit reached. Try again later.",
            }
        }
    assert len(provider.calls) == 7

    async def stored_usage() -> list[str]:
        store = await opened(pg_url)
        try:
            async with store.pool.connection() as conn:
                rows = await (
                    await conn.execute(
                        "SELECT to_jsonb(provider_usage)::text AS data FROM provider_usage "
                        "WHERE owner_user_id=%s",
                        (owner,),
                    )
                ).fetchall()
            return [row["data"] for row in rows]
        finally:
            await store.close()

    rows = asyncio.run(stored_usage())
    assert len(rows) == 7
    assert all(headers["x-forwarded-for"] not in row for row in rows)
    assert all("fake-key" not in row and "The method improved" not in row for row in rows)


def test_hosted_revision_cap_and_idempotent_replay(
    pg_url: str, local_pg_api: None, monkeypatch
) -> None:
    monkeypatch.setenv("VERCEL", "1")
    app = create_app(hosted_settings(pg_url))
    provider = RevisionProvider()
    app.state.judgment_provider = provider
    install_auth_mock(app)
    owner = str(uuid4())
    headers = {
        "Authorization": f"Bearer {owner}",
        "x-forwarded-for": str(ipaddress.IPv4Address(uuid4().int & 0xFFFFFFFF)),
    }
    with TestClient(app) as client:
        initial = client.post("/api/v1/audits", json=audit_body(), headers=headers)
        assert initial.status_code == 201
        audit = initial.json()
        audit_id = audit["audit_id"]
        for index in range(5):
            body = {
                "proposal_id": audit["current_proposal_id"],
                "proposal_version": audit["current_proposal_version"],
                "expected_state_revision": audit["state_revision"],
                "idempotency_key": f"revision-{index}-{uuid4()}",
                "reviewer": "r",
                "feedback": "Recheck the secondary-task boundary.",
            }
            path = f"/api/v1/audits/{audit_id}/revisions"
            result = client.post(path, json=body, headers=headers)
            assert result.status_code == 200
            assert result.json()["status"] == "revision_completed"
            replay = client.post(path, json=body, headers=headers)
            assert replay.status_code == 200
            assert replay.json()["revision_id"] == result.json()["revision_id"]
            audit = client.get(f"/api/v1/audits/{audit_id}", headers=headers).json()
        sixth = client.post(
            path,
            json={
                **body,
                "proposal_id": audit["current_proposal_id"],
                "proposal_version": audit["current_proposal_version"],
                "expected_state_revision": audit["state_revision"],
                "idempotency_key": str(uuid4()),
            },
            headers=headers,
        )
        assert sixth.status_code == 429
        assert sixth.json()["detail"]["scope"] == "audit_revision"
    assert len(provider.calls) == 6


@pytest.mark.asyncio
async def test_provider_failure_records_only_sanitized_code(pg_url: str) -> None:
    store = await opened(pg_url)
    try:

        class FailingProvider(RevisionProvider):
            async def evaluate(self, *args, **kwargs):
                raise ProviderError("upstream response with private claim text")

        owner, ip_hash = str(uuid4()), uuid4().hex
        provider = MeteredProvider(
            FailingProvider(), PostgresUsageGuard(store.pool), owner, ip_hash, "audit"
        )
        with pytest.raises(ProviderError):
            await provider.evaluate("private claim text", "private evidence text")
        async with store.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT to_jsonb(provider_usage) AS data FROM provider_usage "
                    "WHERE owner_user_id=%s",
                    (owner,),
                )
            ).fetchone()
        data = row["data"]
        assert data["status"] == "failed" and data["error_code"] == "provider_error"
        assert "private claim text" not in str(data)
        assert "private evidence text" not in str(data)
    finally:
        await store.close()
