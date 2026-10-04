from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any, Protocol, cast

from claim_trellis.retrieval import retrieve

from .dataset import Dataset, Query, passage_id


class RetrieverProtocol(Protocol):
    name: str

    def search(self, query: Query, top_k: int) -> list[str]: ...


class EncoderProtocol(Protocol):
    provenance: dict[str, Any]

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


class LexicalRetriever:
    name = "lexical-evidence-v2"

    def __init__(self, dataset: Dataset) -> None:
        self.dataset = dataset

    def search(self, query: Query, top_k: int) -> list[str]:
        source = self.dataset.sources[query.source_id]
        return [
            passage_id(query.source_id, c.passage.passage_id)
            for c in retrieve(
                query.text, source.text, blocks=source.blocks, top_k=top_k, citation=query.citation
            )
        ]


def normalized(vectors: list[list[float]], expected: int) -> list[list[float]]:
    if len(vectors) != expected or not vectors:
        raise ValueError("Encoder returned the wrong number of vectors.")
    dimensions = len(vectors[0])
    result = []
    for vector in vectors:
        if not dimensions or len(vector) != dimensions or not all(map(math.isfinite, vector)):
            raise ValueError("Invalid embedding dimensions or nonfinite values.")
        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0:
            raise ValueError("Zero-norm embedding.")
        result.append([v / norm for v in vector])
    return result


class DenseRetriever:
    name = "dense-experimental"

    def __init__(self, dataset: Dataset, encoder: EncoderProtocol) -> None:
        self.dataset, self.encoder = dataset, encoder
        self.ids = sorted(dataset.passages)
        self.vectors = normalized(
            encoder.encode([dataset.passages[p].text for p in self.ids]), len(self.ids)
        )
        self.index_bytes = len(self.ids) * len(self.vectors[0]) * 8  # logical float64 payload

    def search(self, query: Query, top_k: int) -> list[str]:
        vector = normalized(self.encoder.encode([query.text]), 1)[0]
        if len(vector) != len(self.vectors[0]):
            raise ValueError("Query/index dimensionality mismatch.")
        scored = [
            (sum(a * b for a, b in zip(vector, document, strict=True)), pid)
            for pid, document in zip(self.ids, self.vectors, strict=True)
            if self.dataset.passages[pid].source_id == query.source_id
        ]
        return [pid for _, pid in sorted(scored, key=lambda pair: (-pair[0], pair[1]))[:top_k]]


def rrf(rankings: Sequence[Sequence[str]], *, k: int = 60) -> list[str]:
    if k < 1:
        raise ValueError("RRF k must be positive.")
    scores: dict[str, float] = defaultdict(float)
    for ranking in rankings:
        seen: set[str] = set()
        for rank, pid in enumerate(ranking, 1):
            if pid not in seen:
                scores[pid] += 1 / (k + rank)
                seen.add(pid)
    return sorted(scores, key=lambda pid: (-scores[pid], pid))


class HybridRetriever:
    name = "hybrid-rrf-experimental"

    def __init__(self, lexical: LexicalRetriever, dense: DenseRetriever, *, k: int = 60) -> None:
        if k < 1:
            raise ValueError("RRF k must be positive.")
        self.lexical, self.dense, self.k = lexical, dense, k

    def search(self, query: Query, top_k: int) -> list[str]:
        # Equal rank contribution, never add BM25 and cosine scores.
        return rrf([self.lexical.search(query, top_k), self.dense.search(query, top_k)], k=self.k)[
            :top_k
        ]


class SentenceEncoder:
    def __init__(self, model: str, revision: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("Pin an immutable 40-character embedding model commit SHA.")
        # Optional, offline-only dependency. Never imported by claim_trellis.
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            model, revision=revision, device="cpu", trust_remote_code=False
        )
        self.provenance = {
            "embedding_model": model,
            "embedding_model_revision": revision,
            "device": "cpu",
            "distance_function": "cosine",
            "index_settings": {"type": "exact-flat", "normalization": "l2", "dtype": "float64"},
            "max_seq_length": self.model.max_seq_length,
            "truncated_inputs": 0,
            "external_api_calls": 0,
            "external_api_cost_usd": 0,
            "local_compute_cost_usd": None,
        }

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        for text in texts:
            count = len(self.model.tokenizer.encode(text, truncation=False))
            self.provenance["truncated_inputs"] += int(count > self.model.max_seq_length)
        return cast(
            list[list[float]],
            self.model.encode(
                list(texts), normalize_embeddings=True, show_progress_bar=False
            ).tolist(),
        )
