from __future__ import annotations

import math
from statistics import mean
from time import perf_counter
from typing import Any

from .dataset import SLICES, Dataset
from .retrievers import RetrieverProtocol


def metrics(ranking: list[str], qrels: dict[str, int]) -> dict[str, float]:
    if len(ranking) != len(set(ranking)):
        raise ValueError("Duplicate result IDs are not valid rankings.")
    relevant = {pid for pid, score in qrels.items() if score > 0}
    if not relevant:
        raise ValueError("Recall needs at least one relevant passage.")
    result = {f"Recall@{k}": len(set(ranking[:k]) & relevant) / len(relevant) for k in (1, 5, 10)}
    result["MRR@10"] = next(
        (1 / rank for rank, pid in enumerate(ranking[:10], 1) if pid in relevant), 0
    )
    gains = [2 ** qrels.get(pid, 0) - 1 for pid in ranking[:10]]
    ideal = sorted((2**score - 1 for score in qrels.values()), reverse=True)[:10]
    result["nDCG@10"] = sum(gain / math.log2(i + 2) for i, gain in enumerate(gains)) / sum(
        gain / math.log2(i + 2) for i, gain in enumerate(ideal)
    )
    return result


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        return {"query_count": 0, "metrics": None}
    return {
        "query_count": len(records),
        "metrics": {key: mean(r["metrics"][key] for r in records) for key in records[0]["metrics"]},
    }


def evaluate(
    dataset: Dataset, retriever: RetrieverProtocol, *, split: str, top_k: int = 10
) -> dict[str, Any]:
    if top_k < 10:
        raise ValueError("top_k must be at least 10 for the reported metrics.")
    records: list[dict[str, Any]] = []
    for query in sorted(dataset.queries.values(), key=lambda q: q.id):
        if query.split != split:
            continue
        started = perf_counter()
        ranking = retriever.search(query, top_k)
        elapsed = (perf_counter() - started) * 1000
        if len(ranking) > top_k or any(
            pid not in {p.id for p in dataset.pool(query.source_id)} for pid in ranking
        ):
            raise ValueError("Retriever returned out-of-pool result IDs.")
        records.append(
            {
                "query_id": query.id,
                "ranking": ranking,
                "latency_ms": elapsed,
                "metrics": metrics(ranking, dataset.qrels[query.id]),
            }
        )
    slices = {}
    for name in SLICES:
        subset = [r for r in records if name in dataset.queries[r["query_id"]].slices]
        slices[name] = aggregate(subset)
        negatives = [
            (r, dataset.queries[r["query_id"]].hard_negatives.get(name, [])) for r in subset
        ]
        negatives = [(r, ids) for r, ids in negatives if ids]
        slices[name]["negative_query_count"] = len(negatives)
        slices[name]["hard_negative_exposure@5"] = (
            mean(bool(set(r["ranking"][:5]) & set(ids)) for r, ids in negatives)
            if negatives
            else None
        )
    latency = sorted(r["latency_ms"] for r in records)
    return {
        "baseline": retriever.name,
        "split": split,
        **aggregate(records),
        "slices": slices,
        "latency_ms": {
            "p50": latency[len(latency) // 2],
            "p95": latency[math.ceil(len(latency) * 0.95) - 1],
        },
        "queries": records,
    }
