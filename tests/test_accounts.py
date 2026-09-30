"""Account profile contract with real PostgreSQL and mocked Supabase identity."""

from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from claim_trellis import api as api_module
from claim_trellis.accounts import PostgresAccountProfiles
from claim_trellis.api import create_app
from claim_trellis.auth import AuthPrincipal
from claim_trellis.config import Settings
from claim_trellis.postgres_store import PostgresAuditStore

pytest_plugins = ["test_postgres_store"]


@pytest.mark.asyncio
async def test_profile_sync_stores_only_verified_server_identity(pg_url: str) -> None:
    store = PostgresAuditStore(pg_url, sslmode="disable")
    await store.open()
    profiles = PostgresAccountProfiles(store.pool)
    owner = str(uuid4())
    try:
        unverified = AuthPrincipal(
            user_id=owner,
            is_anonymous=False,
            email=None,
            email_verified=False,
            primary_auth_method="email",
        )
        first = await profiles.sync(unverified)
        assert first["product_updates_opt_in"] is False
        verified = AuthPrincipal(
            user_id=owner,
            is_anonymous=False,
            email="reader@example.com",
            email_verified=True,
            primary_auth_method="google",
        )
        second = await profiles.sync(verified)
        assert second["created_at"] == first["created_at"]
        async with store.pool.connection() as conn:
            row = await (
                await conn.execute(
                    "SELECT user_email,email_verified,primary_auth_method,product_updates_opt_in "
                    "FROM user_profiles WHERE user_id=%s",
                    (owner,),
                )
            ).fetchone()
        assert row == {
            "user_email": "reader@example.com",
            "email_verified": True,
            "primary_auth_method": "google",
            "product_updates_opt_in": False,
        }
    finally:
        await store.close()


def test_account_api_uses_verified_principal_and_rejects_guest(pg_url: str, monkeypatch) -> None:
    class LocalPostgresAuditStore(PostgresAuditStore):
        def __init__(self, database_url: str) -> None:
            super().__init__(database_url, sslmode="disable")

    monkeypatch.setattr(api_module, "PostgresAuditStore", LocalPostgresAuditStore)
    app = create_app(
        Settings(
            database_url=pg_url,
            auth_mode="supabase",
            supabase_url="https://example.supabase.co",
            supabase_publishable_key="sb_publishable_test",
            account_access_enabled=True,
        )
    )
    users = {
        "guest": {"id": str(uuid4()), "is_anonymous": True, "email": "untrusted@example.com"},
        "unverified": {
            "id": str(uuid4()),
            "is_anonymous": False,
            "email": "unverified@example.com",
        },
        "verified": {
            "id": str(uuid4()),
            "is_anonymous": False,
            "email": "reader@example.com",
            "email_confirmed_at": "2026-01-01T00:00:00Z",
            "app_metadata": {"provider": "google"},
            "identities": [{"provider": "google"}],
        },
    }

    async def auth(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        return httpx.Response(200, json=users[token]) if token in users else httpx.Response(401)

    app.state.auth_transport = httpx.MockTransport(auth)
    with TestClient(app) as client:
        assert client.get("/api/v1/account").status_code == 401
        assert (
            client.post(
                "/api/v1/account/sync", headers={"Authorization": "Bearer guest"}
            ).status_code
            == 403
        )
        unverified = client.post(
            "/api/v1/account/sync", headers={"Authorization": "Bearer unverified"}
        ).json()
        assert unverified["user_email"] is None and unverified["email_verified"] is False
        verified = client.post(
            "/api/v1/account/sync",
            headers={"Authorization": "Bearer verified"},
            json={"product_updates_opt_in": True, "user_email": "forged@example.com"},
        ).json()
        assert verified["user_id"] == users["verified"]["id"]
        assert verified["user_email"] == "reader@example.com"
        assert verified["connected_methods"] == ["google"]
        assert verified["product_updates_opt_in"] is False
        assert verified["created_at"]
        fetched = client.get("/api/v1/account", headers={"Authorization": "Bearer verified"}).json()
        assert fetched == verified
