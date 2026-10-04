import asyncio
import sys

import httpx
import pytest
from test_typesafe_jev import response_body

from claim_trellis.audit import run_audit
from claim_trellis.config import Settings
from claim_trellis.models import AuditRequest
from claim_trellis.providers.typesafe_jev import TypeSafeJevProvider
from experiments.acceptance import live_smoke


def test_live_tool_two_cases_no_keys_reviews_or_configuration_writes(monkeypatch):
    audits, requests = {}, []

    def handler(request):
        requests.append(request)
        path = request.url.path
        if path == "/healthz":
            return httpx.Response(200, json={"hosted_provider_available": True})
        if path == "/api/v1/auth/config":
            return httpx.Response(
                200,
                json={
                    "supabase_url": "https://auth.example.test",
                    "publishable_key": "public-test-key",
                },
            )
        if path == "/auth/v1/signup":
            assert request.headers["apikey"] == "public-test-key"
            return httpx.Response(200, json={"access_token": "test-only-session"})
        if path == "/auth/v1/logout":
            return httpx.Response(204)
        assert request.headers["Authorization"] == "Bearer test-only-session"
        if request.method == "POST":
            import json

            provider = TypeSafeJevProvider(
                api_key="test-only-not-real",
                endpoint="https://api.typesafe.ai/v1/systemone",
                model="jev-1.13.0",
                transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response_body())),
            )
            audit = asyncio.run(
                run_audit(
                    AuditRequest.model_validate_json(request.content),
                    Settings(jev_api_key=None),
                    judgment_provider=provider,
                )
            )
            data = json.loads(audit.model_dump_json())
            audits[audit.audit_id] = data
            return httpx.Response(201, json=data)
        return httpx.Response(200, json=audits[path.split("/")[-1]])

    original = httpx.Client
    monkeypatch.setattr(
        live_smoke.httpx,
        "Client",
        lambda **kwargs: original(**kwargs, transport=httpx.MockTransport(handler)),
    )
    report = live_smoke.run("https://service.example.test")
    assert report["status"] == "live integration smoke passed"
    assert len(report["results"]) == 2 and len(audits) == 2
    assert "test-only-session" not in str(report)
    assert all(a["human_review"] is None for a in audits.values())
    assert all("settings" not in str(r.url) and "reviews" not in str(r.url) for r in requests)


@pytest.mark.parametrize(
    "url",
    [
        "http://service.example.test",
        "https://user:secret@service.example.test",
        "https://service.example.test/path",
        "https://service.example.test/?secret=abc",
    ],
)
def test_smoke_rejects_insecure_credential_or_path_origins(url):
    with pytest.raises(ValueError):
        live_smoke.run(url)


def test_smoke_redacts_failure_bodies_and_requires_opt_in(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError) as error:
        live_smoke.checked(httpx.Response(401, json={"secret": "never-print-me"}))
    assert "never-print-me" not in str(error.value)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "smoke",
            "--origin",
            "https://service.example.test",
            "--output",
            str(tmp_path / "record.json"),
        ],
    )
    monkeypatch.setattr(
        live_smoke, "run", lambda _: pytest.fail("No opt-in: a call must not occur.")
    )
    with pytest.raises(SystemExit):
        live_smoke.main()
