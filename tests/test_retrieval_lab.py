import hashlib
import json
import shutil
from pathlib import Path

import pytest

from experiments.retrieval.dataset import Dataset
from experiments.retrieval.evaluate import evaluate, metrics
from experiments.retrieval.fixtures import generate
from experiments.retrieval.retrievers import (
    DenseRetriever,
    HybridRetriever,
    LexicalRetriever,
    normalized,
    rrf,
)

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/retrieval/synthetic"


class FakeEncoder:
    provenance = {"embedding_model": "test-only", "embedding_model_revision": "fixture"}

    def encode(self, texts):
        return [[float(len(t)), float(sum(map(ord, t))), 1.0] for t in texts]


def rehash(path):
    manifest = json.loads((path / "manifest.json").read_text())
    for name in manifest["files"]:
        manifest["files"][name] = hashlib.sha256((path / name).read_bytes()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))


def test_fixture_generation_is_frozen(tmp_path):
    generate(tmp_path / "new")
    for path in FIXTURE.iterdir():
        assert path.read_bytes() == (tmp_path / "new" / path.name).read_bytes()
    with pytest.raises(ValueError, match="overwrite"):
        generate(tmp_path / "new")


def test_synthetic_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="allow-synthetic"):
        Dataset(FIXTURE)


@pytest.mark.parametrize("baseline", ["lexical", "dense", "hybrid"])
def test_all_baselines_share_pool_metrics_and_slices(baseline):
    dataset = Dataset(FIXTURE, allow_synthetic=True)
    lexical = LexicalRetriever(dataset)
    dense = DenseRetriever(dataset, FakeEncoder())
    retriever = {"lexical": lexical, "dense": dense, "hybrid": HybridRetriever(lexical, dense)}[
        baseline
    ]
    for split in ("dev", "test"):
        result = evaluate(dataset, retriever, split=split)
        assert result["query_count"] == 7
        assert all(0 <= metric <= 1 for metric in result["metrics"].values())
        assert all(v["query_count"] == 1 for v in result["slices"].values())
        assert all(v["negative_query_count"] == 1 for v in result["slices"].values())


def test_metrics_use_all_relevant_and_handle_missing_results():
    assert metrics(["a", "x", "b"], {"a": 1, "b": 1})["Recall@1"] == 0.5
    assert metrics(["x", "b"], {"a": 1, "b": 1})["MRR@10"] == 0.5
    assert metrics([], {"a": 1})["nDCG@10"] == 0
    assert metrics(["b", "a"], {"a": 3, "b": 1})["nDCG@10"] < 1
    with pytest.raises(ValueError, match="Duplicate"):
        metrics(["a", "a"], {"a": 1})
    with pytest.raises(ValueError, match="relevant"):
        metrics([], {"a": 0})


def test_rrf_rank_only_deterministic_ties_and_duplicate_safety():
    assert rrf([["b", "a"], ["a", "b"]]) == ["a", "b"]
    assert rrf([["a", "a", "b"], ["b"]])[0] == "b"
    with pytest.raises(ValueError):
        rrf([], k=0)


@pytest.mark.parametrize(
    "vectors,expected", [([], 1), ([[0, 0]], 1), ([[1, float("nan")]], 1), ([[1], [1, 2]], 2)]
)
def test_invalid_dense_embeddings_fail_closed(vectors, expected):
    with pytest.raises(ValueError):
        normalized(vectors, expected)


@pytest.mark.parametrize(
    "defect",
    [
        "hash",
        "span",
        "work_leak",
        "content_leak",
        "unconfirmed",
        "reviewers",
        "negative",
        "qrel_foreign",
        "qrel_duplicate",
        "parser",
    ],
)
def test_bad_datasets_rejected_before_retrieval(tmp_path, defect):
    path = tmp_path / "dataset"
    shutil.copytree(FIXTURE, path)
    if defect in {"work_leak", "content_leak", "parser"}:
        sources = [json.loads(s) for s in (path / "sources.jsonl").read_text().splitlines()]
        if defect == "work_leak":
            sources[7]["work_id"] = sources[0]["work_id"]
        elif defect == "content_leak":
            for key in ("text", "sha256", "blocks"):
                sources[7][key] = sources[0][key]
        else:
            sources[0]["parser_version"] = "wrong-parser"
        (path / "sources.jsonl").write_text("\n".join(map(json.dumps, sources)))
    elif defect == "span":
        rows = (path / "corpus.jsonl").read_text().splitlines()
        record = json.loads(rows[0])
        record["text"] += " synthetic hallucination"
        rows[0] = json.dumps(record)
        (path / "corpus.jsonl").write_text("\n".join(rows))
    elif defect in {"unconfirmed", "reviewers"}:
        manifest = json.loads((path / "manifest.json").read_text())
        manifest.update(
            annotation_status="human-adjudicated",
            qrels_reviewers=["A", "B"] if defect == "unconfirmed" else ["A", "A"],
            adjudicator="C",
        )
        (path / "manifest.json").write_text(json.dumps(manifest))
    else:
        qrels = (path / "qrels.tsv").read_text()
        if defect == "negative":
            qrels = qrels.replace("\t0\n", "\t1\n")
        elif defect == "qrel_foreign":
            qrels = qrels.replace("query-dev-0", "unknown-query", 1)
        elif defect == "qrel_duplicate":
            qrels += qrels.splitlines()[1] + "\n"
        else:
            qrels += "tamper"
        (path / "qrels.tsv").write_text(qrels)
    if defect != "hash":
        rehash(path)
    with pytest.raises(ValueError):
        Dataset(path, allow_synthetic=True)


def test_experiments_not_imported_by_production():
    root = FIXTURE.parents[2] / "src/claim_trellis"
    assert all("experiments.retrieval" not in p.read_text() for p in root.rglob("*.py"))
