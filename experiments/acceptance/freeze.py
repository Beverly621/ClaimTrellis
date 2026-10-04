import hashlib
import json
from pathlib import Path
from typing import Any

from claim_trellis.checks import CHECK_SET_VERSION
from claim_trellis.chunking import RETRIEVAL_VERSION
from claim_trellis.document_blocks import PARSER_VERSION
from claim_trellis.paper_extraction import EXTRACTION_VERSION
from claim_trellis.paper_references import REFERENCE_VERSION
from claim_trellis.policy import POLICY_VERSION
from claim_trellis.providers.typesafe_jev import (
    QUESTION_SET_VERSION,
    QUESTIONS,
    REVISION_QUESTION_SET_VERSION,
)

ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "paper_models.py",
    "paper_run_models.py",
    "paper_store.py",
    "paper_references.py",
    "paper_extraction.py",
    "paper_runs.py",
    "retrieval.py",
    "chunking.py",
    "document_blocks.py",
    "policy.py",
    "providers/typesafe_jev.py",
)


def snapshot() -> dict[str, Any]:
    return {
        "contract_version": "paper-workflow-p1.5-0005",
        "claim_extraction_version": EXTRACTION_VERSION,
        "reference_parser_version": REFERENCE_VERSION,
        "mapping_version": "p1.3-human-identity-gated",
        "audit_orchestration_version": "p1.4-0005-fenced-checkpoint-v1",
        "retrieval_production_version": RETRIEVAL_VERSION,
        "parser_version": PARSER_VERSION,
        "check_set_version": CHECK_SET_VERSION,
        "question_set_version": QUESTION_SET_VERSION,
        "revision_question_set_version": REVISION_QUESTION_SET_VERSION,
        "questions_sha256": hashlib.sha256(
            json.dumps(QUESTIONS, sort_keys=True).encode()
        ).hexdigest(),
        "policy_version": POLICY_VERSION,
        "requested_model": "jev-1.13.0",
        "code_sha256": {
            name: hashlib.sha256((ROOT / "src/claim_trellis" / name).read_bytes()).hexdigest()
            for name in FILES
        },
    }


if __name__ == "__main__":
    target = ROOT / "tests/fixtures/contracts/workflow-freeze.json"
    if target.exists():
        raise ValueError(
            "Acceptance freeze already exists; changes require explicit blocker review."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(snapshot(), indent=2) + "\n")
