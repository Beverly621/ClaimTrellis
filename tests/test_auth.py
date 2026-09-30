from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from test_storage import example_audit

from claim_trellis.api import create_app
from claim_trellis.config import Settings
from claim_trellis.store import LOCAL_USER_ID, SQLiteAsyncStore

USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


def hosted_settings() -> Settings:
    return Settings(
        database_url="postgresql://postgres:private-password@db.example/claim_trellis_test",
        auth_mode="supabase",
        supabase_url="https://example.supabase.co",
        supabase_publishable_key="sb_publishable_test",
        jev_api_key="private-jev-key",
    )


class IsolatedStore:
    def __init__(self) -> None:
        self.owners: dict[str, str] = {}
        self.audits = {}

    async def save(self, owner_user_id, audit):
        self.owners[audit.audit_id] = owner_user_id
        self.audits[audit.audit_id] = audit
        return audit

    async def get(self, owner_user_id, audit_id):
        return self.audits.get(audit_id) if self.owners.get(audit_id) == owner_user_id else None

    async def list_audits(self, owner_user_id, *, limit=50, offset=0):
        return [
            audit
            for audit_id, audit in self.audits.items()
            if self.owners[audit_id] == owner_user_id
        ][offset : offset + limit]

    async def proposals(self, owner_user_id, audit_id):
        assert self.owners[audit_id] == owner_user_id
        return []

    async def revisions(self, owner_user_id, audit_id):
        assert self.owners[audit_id] == owner_user_id
        return []

    async def events(self, owner_user_id, audit_id):
        assert self.owners[audit_id] == owner_user_id
        return []


def install_auth_mock(app) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in {"token-a", "token-b"}:
            return httpx.Response(401, json={"message": "invalid token"})
        user_id = USER_A if token == "token-a" else USER_B
        return httpx.Response(200, json={"id": user_id, "is_anonymous": True})

    app.state.auth_transport = httpx.MockTransport(handler)


def test_config_is_public_and_never_leaks_secrets() -> None:
    app = create_app(hosted_settings())
    with TestClient(app) as client:
        response = client.get("/api/v1/auth/config")
        health = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": True,
        "provider": "supabase",
        "supabase_url": "https://example.supabase.co",
        "publishable_key": "sb_publishable_test",
    }
    assert health.json()["storage_backend"] == "postgres"
    assert health.json()["auth_mode"] == "supabase"
    assert "private-password" not in str(response.json()) + str(health.json())
    assert "private-jev-key" not in str(response.json()) + str(health.json())


def test_missing_and_invalid_tokens_fail_closed() -> None:
    app = create_app(hosted_settings())
    install_auth_mock(app)
    with TestClient(app) as client:
        assert client.get("/api/v1/audits").status_code == 401
        assert (
            client.get("/api/v1/audits", headers={"Authorization": "Bearer bad"}).status_code == 401
        )
        assert (
            client.post(
                "/api/v1/documents/parse", files={"document": ("a.txt", b"text", "text/plain")}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/v1/evidence/search", json={"claim": "A claim", "source_text": "A source"}
            ).status_code
            == 401
        )


def test_verified_anonymous_users_cannot_list_or_probe_each_others_audits() -> None:
    app = create_app(hosted_settings())
    store = IsolatedStore()
    app.state.lifecycle_store = store
    install_auth_mock(app)
    with TestClient(app) as client:
        a = client.post(
            "/api/v1/audits",
            headers={"Authorization": "Bearer token-a"},
            json={
                "claim": "The method improved accuracy.",
                "source_text": "The method improved accuracy on task one.",
                "owner_user_id": USER_B,
                "use_judgment_provider": False,
            },
        )
        assert a.status_code == 201
        audit_id = a.json()["audit_id"]
        assert store.owners[audit_id] == USER_A
        assert UUID(store.owners[audit_id])
        assert (
            len(client.get("/api/v1/audits", headers={"Authorization": "Bearer token-a"}).json())
            == 1
        )
        assert (
            client.get("/api/v1/audits", headers={"Authorization": "Bearer token-b"}).json() == []
        )
        base = f"/api/v1/audits/{audit_id}"
        other = {"Authorization": "Bearer token-b"}
        for path in (
            base,
            base + "/proposals",
            base + "/proposals/current",
            base + "/revisions",
            base + "/events",
        ):
            assert client.get(path, headers=other).status_code == 404
        assert (
            client.post(
                base + "/reviews",
                headers=other,
                json={"decision": "defer", "notes": "Checked.", "reviewer": "r"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                base + "/revisions",
                headers=other,
                json={
                    "proposal_id": "foreign-proposal",
                    "proposal_version": 1,
                    "expected_state_revision": 0,
                    "idempotency_key": "other-user-key",
                    "reviewer": "r",
                    "feedback": "Recheck.",
                },
            ).status_code
            == 404
        )


@pytest.mark.asyncio
async def test_local_sqlite_adapter_uses_local_owner_only(tmp_path) -> None:
    store = SQLiteAsyncStore(tmp_path / "audits.db")
    audit = await store.save(LOCAL_USER_ID, example_audit())
    assert await store.get(LOCAL_USER_ID, audit.audit_id) is not None
    assert await store.get(USER_B, audit.audit_id) is None
    assert len(await store.list_audits(LOCAL_USER_ID)) == 1
    with pytest.raises(KeyError):
        await store.proposals(USER_B, audit.audit_id)


def test_hosted_runtime_requires_complete_auth_config() -> None:
    with pytest.raises(ValueError, match="Supabase authentication"):
        create_app(Settings(database_url="postgresql://localhost/test"))
    with pytest.raises(ValueError, match="publishable key"):
        create_app(Settings(database_url="postgresql://localhost/test", auth_mode="supabase"))
