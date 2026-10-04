"""BEIR-shaped IDs with additional exact-span and annotation safeguards."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from claim_trellis.document_blocks import PARSER_VERSION, validate_blocks
from claim_trellis.models import DocumentBlock
from claim_trellis.retrieval import retrieve

SLICES = (
    "population_mismatch",
    "outcome_mismatch",
    "direction_mismatch",
    "numeric_mismatch",
    "causal_mismatch",
    "timeframe_mismatch",
    "same_terminology_wrong_study",
)
Split = Literal["dev", "test"]


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


R = TypeVar("R", bound=Record)


class Source(Record):
    source_id: str = Field(min_length=1)
    # Canonical paper identity shared by all uploaded versions (DOI where available).
    work_id: str = Field(min_length=1)
    split: Split
    text: str = Field(min_length=1)
    sha256: str
    blocks: list[DocumentBlock]
    parser_version: str
    license: str = Field(min_length=1)


class Passage(Record):
    id: str = Field(alias="_id", min_length=1)
    source_id: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    sha256: str


class Query(Record):
    id: str = Field(alias="_id", min_length=1)
    source_id: str
    split: Split
    text: str = Field(min_length=3)
    human_confirmed: bool
    reviewer: str | None = None
    citation: str | None = None
    slices: list[str] = Field(default_factory=list)
    hard_negatives: dict[str, list[str]] = Field(default_factory=dict)


class Manifest(Record):
    schema_version: Literal["claim-trellis-retrieval-v1"]
    dataset_version: str = Field(min_length=1)
    annotation_status: Literal["synthetic-engineering", "human-adjudicated"]
    qrels_reviewers: list[str]
    adjudicator: str | None
    retrieval_scope: Literal["within-identified-source"]
    parser_version: str
    retrieval_version: Literal["lexical-evidence-v2"]
    files: dict[str, str]
    notes: str


def passage_id(source_id: str, production_id: str) -> str:
    return f"{source_id}/{production_id}"


def frozen_passages(source: Source) -> list[Passage]:
    """Export the actual production v2 context spans, not a substitute chunker."""
    return [
        Passage(
            _id=passage_id(source.source_id, c.passage.passage_id),
            source_id=source.source_id,
            text=c.passage.text,
            start=c.passage.start_char,
            end=c.passage.end_char,
            sha256=c.passage.sha256,
        )
        for c in retrieve("", source.text, blocks=source.blocks, top_k=100_000)
    ]


def rows(path: Path, model: type[R]) -> list[R]:
    return [model.model_validate_json(line) for line in path.read_text().splitlines() if line]


def unique(records: list[R], key: str) -> dict[str, R]:
    result = {str(getattr(row, key)): row for row in records}
    if len(result) != len(records) or not result:
        raise ValueError("Empty dataset or duplicate IDs.")
    return result


class Dataset:
    def __init__(self, path: Path, *, allow_synthetic: bool = False) -> None:
        self.manifest = Manifest.model_validate_json((path / "manifest.json").read_text())
        expected = {"sources.jsonl", "corpus.jsonl", "queries.jsonl", "qrels.tsv"}
        if set(self.manifest.files) != expected:
            raise ValueError(
                "Manifest must freeze all four data files, including source snapshots."
            )
        for name, digest in self.manifest.files.items():
            if hashlib.sha256((path / name).read_bytes()).hexdigest() != digest:
                raise ValueError(f"Frozen file hash mismatch: {name}")
        synthetic = self.manifest.annotation_status == "synthetic-engineering"
        if synthetic and not allow_synthetic:
            raise ValueError("Synthetic engineering fixtures require explicit --allow-synthetic.")
        if not synthetic and (
            len({name.strip() for name in self.manifest.qrels_reviewers if name.strip()}) < 2
            or not (self.manifest.adjudicator or "").strip()
        ):
            raise ValueError("Formal qrels require two independent reviewers and an adjudicator.")
        if self.manifest.parser_version != PARSER_VERSION:
            raise ValueError("Parser version differs from the frozen production baseline.")
        self.sources = unique(rows(path / "sources.jsonl", Source), "source_id")
        self.passages = unique(rows(path / "corpus.jsonl", Passage), "id")
        self.queries = unique(rows(path / "queries.jsonl", Query), "id")
        works: dict[str, str] = {}
        hashes: dict[str, str] = {}
        expected_passages = {}
        for s in self.sources.values():
            if s.sha256 != sha(s.text) or s.parser_version != self.manifest.parser_version:
                raise ValueError("Source hash/parser mismatch.")
            validate_blocks(s.text, s.blocks)
            work = s.work_id.strip().lower()
            for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
                work = work.removeprefix(prefix).strip()
            if not work:
                raise ValueError("Canonical work identity cannot be blank.")
            for identities, key in ((works, work), (hashes, s.sha256)):
                if key in identities and identities[key] != s.split:
                    raise ValueError("Source/work leakage across dev and test.")
                identities[key] = s.split
            expected_passages.update({p.id: p for p in frozen_passages(s)})
        if self.passages != expected_passages:
            raise ValueError("Corpus must match all exact production-v2 context spans.")
        self.qrels: dict[str, dict[str, int]] = {q: {} for q in self.queries}
        with (path / "qrels.tsv").open(newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != ["query-id", "corpus-id", "score"]:
                raise ValueError("Qrels header must be query-id, corpus-id, score.")
            for r in reader:
                qid, pid, score = r["query-id"], r["corpus-id"], int(r["score"])
                if qid not in self.queries or pid not in self.passages or score not in {0, 1, 2, 3}:
                    raise ValueError("Unknown qrel ID or unsupported relevance grade.")
                q, p = self.queries[qid], self.passages[pid]
                if p.source_id != q.source_id or pid in self.qrels[qid]:
                    raise ValueError("Cross-source or duplicate qrel.")
                self.qrels[qid][pid] = score
        for q in self.queries.values():
            if q.source_id not in self.sources or self.sources[q.source_id].split != q.split:
                raise ValueError("Query/source split mismatch.")
            if not synthetic and (not q.human_confirmed or not (q.reviewer or "").strip()):
                raise ValueError("Formal queries must be human-confirmed atomic claims.")
            if not any(self.qrels[q.id].values()):
                raise ValueError("Every query needs at least one relevant passage.")
            if set(q.slices) - set(SLICES) or set(q.hard_negatives) - set(q.slices):
                raise ValueError("Unknown or inconsistent hard-negative slice.")
            for negatives in q.hard_negatives.values():
                for pid in negatives:
                    if self.qrels[q.id].get(pid) != 0:
                        raise ValueError("Hard negatives must have an explicit non-relevant qrel.")
        if {q.split for q in self.queries.values()} != {"dev", "test"}:
            raise ValueError("Both dev and test must be present.")
        self.split_hash = sha(
            json.dumps(
                sorted((s.source_id, s.work_id, s.sha256, s.split) for s in self.sources.values())
            )
        )

    def pool(self, source_id: str) -> list[Passage]:
        return [p for p in self.passages.values() if p.source_id == source_id]
