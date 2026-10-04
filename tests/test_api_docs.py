"""API explorer exposure is separate from authentication and endpoint contracts."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claim_trellis.api import create_app
from claim_trellis.config import Settings

HOSTED = {
    "auth_mode": "supabase",
    "database_url": "postgresql://test-only.invalid/unused",
    "supabase_url": "https://example.supabase.co",
    "supabase_publishable_key": "public-test-key",
}


@pytest.mark.parametrize("override", [None, True, False])
@pytest.mark.parametrize("hosted", [False, True])
def test_docs_routes_follow_explicit_override_or_safe_defaults(tmp_path, override, hosted):
    settings = Settings(data_dir=tmp_path, api_docs_enabled=override, **(HOSTED if hosted else {}))
    app = create_app(settings)
    enabled = override if override is not None else not hosted
    # No lifespan is entered: the unused PostgreSQL test URL is never connected.
    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == (200 if enabled else 404)
    assert client.get("/").status_code == 200
    assert client.get("/projects").status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/auth/config").status_code == 200
    if hosted:
        assert client.get("/api/v1/projects").status_code == 401
        assert client.get("/api/v1/audits").status_code == 401
    # Generation remains available to tooling; hiding explorer routes is not an
    # authentication mechanism and does not remove or modify endpoint contracts.
    schema = app.openapi()
    assert "/api/v1/audits" in schema["paths"]
    assert "/api/v1/projects" in schema["paths"]


def test_schema_and_functional_workflow_unchanged_when_local_docs_disabled(tmp_path):
    enabled = create_app(Settings(data_dir=tmp_path / "on", api_docs_enabled=True))
    disabled = create_app(Settings(data_dir=tmp_path / "off", api_docs_enabled=False))
    assert enabled.openapi() == disabled.openapi()
    with TestClient(disabled) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "Explorer-independent project", "idempotency_key": "docs-off-project"},
        )
        assert project.status_code == 201
        audit = client.post(
            "/api/v1/audits",
            json={
                "claim": "The fictional trial enrolled 40 adults.",
                "source_text": "The fictional trial enrolled 40 adults.",
                "source": {"access_tier": "excerpt"},
                "use_judgment_provider": False,
            },
        )
        assert audit.status_code == 201
        assert client.get(f"/api/v1/audits/{audit.json()['audit_id']}").status_code == 200


def test_docs_environment_flag_and_hosted_provider_default(monkeypatch):
    monkeypatch.setenv("CLAIM_TRELLIS_API_DOCS_ENABLED", "false")
    assert Settings().resolved_api_docs_enabled is False
    monkeypatch.setenv("CLAIM_TRELLIS_API_DOCS_ENABLED", "true")
    assert Settings(**HOSTED).resolved_api_docs_enabled is True
    monkeypatch.delenv("CLAIM_TRELLIS_API_DOCS_ENABLED")
    assert Settings(hosted_provider_enabled=True).resolved_api_docs_enabled is False


@pytest.mark.parametrize("override", [None, "true"])
def test_vercel_adapter_closes_docs_even_without_postgres_config(tmp_path, override):
    env = {"PATH": os.environ.get("PATH", ""), "CLAIM_TRELLIS_DATA_DIR": str(tmp_path)}
    if override is not None:
        env["CLAIM_TRELLIS_API_DOCS_ENABLED"] = override
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from src.vercel_app import app; "
            "print(json.dumps([app.docs_url, app.redoc_url, app.openapi_url]))",
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert json.loads(result.stdout) == (
        ["/docs", "/redoc", "/openapi.json"] if override else [None, None, None]
    )
