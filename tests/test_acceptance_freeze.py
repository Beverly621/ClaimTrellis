import json
from pathlib import Path

from experiments.acceptance.freeze import snapshot


def test_frozen_p1_algorithms_and_contracts_unchanged():
    path = Path(__file__).resolve().parent / "fixtures/contracts/workflow-freeze.json"
    assert snapshot() == json.loads(path.read_text()), (
        "Algorithm/contract change requires blocker review and explicit freeze update."
    )
