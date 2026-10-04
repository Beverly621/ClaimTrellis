"""Opt-in two-case hosted integration smoke. No keys, accuracy scoring or review."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from claim_trellis.models import ClaimAudit
from claim_trellis.providers.typesafe_jev import QUESTIONS

CASES = [
    ("The fictional trial enrolled 40 adults.", "The fictional trial enrolled 40 adults."),
    (
        "The fictional intervention increased the measured endpoint.",
        "The fictional intervention decreased the measured endpoint.",
    ),
]


def checked(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 400:
        # Never print bodies that might contain tokens/provider/database diagnostics.
        raise RuntimeError(f"Integration smoke stopped: HTTP {response.status_code}.")
    return cast(dict[str, Any], response.json())


def run(origin: str) -> dict[str, Any]:
    if urlparse(origin).scheme != "https" or urlparse(origin).path not in {"", "/"}:
        raise ValueError("Use an HTTPS service origin without path/query/credentials.")
    if urlparse(origin).username or urlparse(origin).query or urlparse(origin).fragment:
        raise ValueError("Do not put credentials or query data in the service origin.")
    with httpx.Client(base_url=origin, follow_redirects=True, timeout=180) as client:
        health = checked(client.get("/healthz"))
        if not health.get("hosted_provider_available"):
            raise RuntimeError(
                "Hosted provider unavailable; no call attempted or configuration changed."
            )
        config = checked(client.get("/api/v1/auth/config"))
        auth_url = config["supabase_url"].rstrip("/")
        if urlparse(auth_url).scheme != "https":
            raise ValueError("Authentication must use HTTPS.")
        # One ordinary synthetic Guest workspace. No user session/real API key is read.
        session = checked(
            client.post(
                auth_url + "/auth/v1/signup",
                headers={"apikey": config["publishable_key"]},
                json={"data": {"purpose": "ClaimTrellis P1.7 synthetic integration smoke"}},
            )
        )
        token = session["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        results = []
        for i, (claim, evidence) in enumerate(CASES, 1):
            data = checked(
                client.post(
                    "/api/v1/audits",
                    json={
                        "claim": claim,
                        "source_text": evidence,
                        "source": {
                            "title": f"P1.7 invented integration case {i}",
                            "access_tier": "excerpt",
                        },
                        "use_judgment_provider": True,
                    },
                )
            )
            audit = ClaimAudit.model_validate(data)
            judgment = audit.judgment_result
            if audit.service_errors or judgment is None:
                raise RuntimeError(
                    "Live provider failed; no accuracy result or automatic retry audit is recorded."
                )
            assert judgment.provider == "typesafe_jev"
            assert judgment.requested_model == "jev-1.13.0" == audit.provenance.requested_model
            assert judgment.resolved_model == audit.provenance.resolved_model
            assert (
                judgment.question_set_version
                == audit.provenance.question_set_version
                == "claim-source-en-v3"
            )
            assert set(judgment.raw_answers) == set(QUESTIONS)
            assert judgment.input_tokens > 0 and judgment.output_tokens >= 0
            assert audit.provenance.retrieval_version == "lexical-evidence-v2"
            assert audit.human_review is None and not audit.proposal.auto_accepted
            # Persisted records, protected access and raw answers are part of the smoke.
            persisted = checked(client.get(f"/api/v1/audits/{audit.audit_id}"))
            assert persisted == data
            results.append(
                {
                    "case": i,
                    "audit_id": audit.audit_id,
                    "integration": "passed",
                    "requested_model": judgment.requested_model,
                    "resolved_model": judgment.resolved_model,
                    "question_set_version": judgment.question_set_version,
                    "answer_count": len(judgment.raw_answers),
                    "input_tokens": judgment.input_tokens,
                    "output_tokens": judgment.output_tokens,
                    "retry_count": judgment.retry_count,
                    "latency_ms": judgment.latency_ms,
                }
            )
        # End only the throwaway smoke session. This does not touch owner sessions or
        # delete the synthetic audit records. Preserve the records for operator inspection.
        client.post(
            auth_url + "/auth/v1/logout?scope=local", headers={"apikey": config["publishable_key"]}
        )
        client.headers.pop("Authorization")
    return {
        "status": "live integration smoke passed",
        "created_at": datetime.now(UTC).isoformat(),
        "intentional_audit_requests": len(CASES),
        "service": origin,
        "results": results,
        "limitation": "Integration only: no scientific accuracy, false-support, or human final judgment. Timeout/retry fault injection is mocked, not induced against the paid service. Synthetic Guest/audits remain stored under normal retention.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--allow-hosted-calls", action="store_true")
    args = parser.parse_args()
    if not args.allow_hosted_calls:
        parser.error(
            "This consumes two hosted audit requests; explicit --allow-hosted-calls required."
        )
    if args.output.exists():
        parser.error("Do not overwrite a smoke record.")
    report = run(args.origin)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"{report['status']}; {report['intentional_audit_requests']} requests. Sanitized record: {args.output}"
    )


if __name__ == "__main__":
    main()
