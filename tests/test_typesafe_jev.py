import json

import httpx
import pytest

from claim_trellis.providers.typesafe_jev import QUESTIONS, TypeSafeJevProvider, build_request


def response_body() -> dict[str, object]:
    body = {
        "model": "jev-1.13.0",
        "answers": {
            "relation": {
                "type": "choice",
                "choice": "supports",
                "probabilities": {
                    "supports": 0.95,
                    "partially_supports": 0.02,
                    "contradicts": 0.01,
                    "not_addressed": 0.01,
                    "insufficient_context": 0.01,
                    "source_unavailable": 0.0,
                },
                "confidence": 0.94,
            },
            "scope_alignment": {
                "type": "choice",
                "choice": "aligned",
                "probabilities": {
                    "aligned": 0.96,
                    "claim_broader": 0.01,
                    "claim_narrower": 0.01,
                    "mismatch": 0.01,
                    "unclear": 0.01,
                },
                "confidence": 0.95,
            },
            "population_alignment": {
                "type": "choice",
                "choice": "not_applicable",
                "probabilities": {
                    "aligned": 0.01,
                    "mismatch": 0.01,
                    "not_applicable": 0.97,
                    "unclear": 0.01,
                },
                "confidence": 0.96,
            },
            "causal_fidelity": {
                "type": "choice",
                "choice": "not_applicable",
                "probabilities": {
                    "faithful": 0.01,
                    "overstated": 0.01,
                    "not_applicable": 0.97,
                    "unclear": 0.01,
                },
                "confidence": 0.96,
            },
            "context_sufficiency": {"type": "noul", "noul": 0.98},
            "prompt_injection": {"type": "noul", "noul": 0.01},
        },
        "usage": {"input_tokens": 411, "output_tokens": 25},
    }
    for key in (
        "claim_type",
        "intervention_or_exposure_alignment",
        "comparator_alignment",
        "outcome_alignment",
        "timeframe_alignment",
        "direction_alignment",
    ):
        chosen = "result" if key == "claim_type" else "aligned"
        body["answers"][key] = {
            "type": "choice",
            "choice": chosen,
            "confidence": 0.96,
            "probabilities": {
                option: float(option == chosen) for option in QUESTIONS[key]["criteria"]
            },
        }
    return body


def test_request_asks_parallel_atomic_questions() -> None:
    payload = build_request("claim", "evidence", "doi:test", "jev-1.13.0")
    assert payload["model"] == "jev-1.13.0"
    assert set(payload["questions"]) == {
        "relation",
        "scope_alignment",
        "population_alignment",
        "causal_fidelity",
        "context_sufficiency",
        "prompt_injection",
        "claim_type",
        "intervention_or_exposure_alignment",
        "comparator_alignment",
        "outcome_alignment",
        "timeframe_alignment",
        "direction_alignment",
    }


@pytest.mark.asyncio
async def test_provider_parses_typed_response_without_exposing_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        request_json = json.loads(request.content)
        assert request_json["state"]["claim"] == "claim"
        return httpx.Response(200, json=response_body())

    client = TypeSafeJevProvider(
        api_key="secret",
        endpoint="https://api.typesafe.ai/v1/systemone",
        model="jev-1.13.0",
        transport=httpx.MockTransport(handler),
    )
    result = await client.evaluate("claim", "evidence")
    assert result.provider == "typesafe_jev"
    assert result.relation.choice == "supports"
    assert result.input_tokens == 411
