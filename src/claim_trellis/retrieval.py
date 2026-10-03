from __future__ import annotations

import math
import re
from collections import Counter

from claim_trellis.chunking import chunk_text
from claim_trellis.document_blocks import text_blocks, validate_blocks
from claim_trellis.models import DocumentBlock, EvidencePassage, RetrievedCandidate

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{1,}|\d+(?:\.\d+)?")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "were",
    "with",
}


def tokenize(text: str) -> list[str]:
    return [
        token
        for token in (match.group(0).lower() for match in TOKEN_RE.finditer(text))
        if token not in STOPWORDS
    ]


def rank_passages(
    claim: str,
    passages: list[EvidencePassage],
    *,
    top_k: int = 10,
    k1: float = 1.5,
    b: float = 0.75,
) -> list[RetrievedCandidate]:
    if not passages:
        return []
    query = list(dict.fromkeys(tokenize(claim)))
    documents = [tokenize(passage.text) for passage in passages]
    average_length = sum(len(document) for document in documents) / len(documents) or 1.0
    document_frequency = Counter(token for document in documents for token in set(document))
    scored: list[tuple[float, EvidencePassage]] = []
    for passage, document in zip(passages, documents, strict=True):
        frequencies = Counter(document)
        score = 0.0
        for token in query:
            frequency = frequencies[token]
            if not frequency:
                continue
            df = document_frequency[token]
            inverse = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = frequency + k1 * (1 - b + b * len(document) / average_length)
            score += inverse * (frequency * (k1 + 1)) / denominator
        # Only boost passages with lexical overlap; no metadata-only false retrieval.
        if score > 0:
            coverage = sum(token in frequencies for token in query) / max(len(query), 1)
            numeric = sum(
                bool(re.fullmatch(r"\d+(?:\.\d+)?", token))
                for token in query
                if token in frequencies
            )
            rare = sum(1 / document_frequency[token] for token in query if token in frequencies)
            normalized = " ".join(tokenize(passage.text))
            phrases = sum(" ".join(query[i : i + 3]) in normalized for i in range(len(query) - 2))
            section = (passage.section or "").lower()
            section_weight = (
                0.15 if any(term in section for term in ("result", "discussion")) else 0
            )
            score += coverage * 2 + numeric * 0.5 + rare * 0.2 + phrases * 0.3 + section_weight
        scored.append((score, passage))
    scored.sort(key=lambda item: (-item[0], item[1].start_char))
    unique: list[tuple[float, EvidencePassage]] = []
    hashes: set[str] = set()
    for item in scored:
        if item[1].sha256 not in hashes:
            unique.append(item)
            hashes.add(item[1].sha256)
    return [
        RetrievedCandidate(passage=passage, score=round(score, 8), rank=rank)
        for rank, (score, passage) in enumerate(unique[:top_k], start=1)
    ]


def retrieve(
    claim: str,
    source_text: str,
    *,
    top_k: int = 10,
    blocks: list[DocumentBlock] | None = None,
    citation: str | None = None,
) -> list[RetrievedCandidate]:
    blocks = blocks or text_blocks(source_text)
    validate_blocks(source_text, blocks)
    passages: list[EvidencePassage] = []
    for block in blocks:
        if block.block_type == "heading":
            continue
        for passage in chunk_text(block.text, target_chars=900, max_chars=1600):
            start = block.char_start + passage.start_char
            end = block.char_start + passage.end_char
            passages.append(
                passage.model_copy(
                    update={
                        "start_char": start,
                        "end_char": end,
                        "passage_id": f"p-{start}-{end}-{passage.sha256[:12]}",
                        "locator": f"{block.locator} / chars:{start}-{end}",
                        "block_ids": [block.block_id],
                        "page": block.page,
                        "section": block.section,
                        "paragraph": block.paragraph,
                    }
                )
            )
    candidates = rank_passages(claim, passages, top_k=len(passages))
    # Citation proximity is an explicit exact-match feature, not source identity proof.
    if citation:
        candidates = [
            item.model_copy(update={"score": item.score + 0.3})
            if item.score > 0 and citation.lower() in item.passage.text.lower()
            else item
            for item in candidates
        ]
        candidates.sort(key=lambda item: (-item.score, item.passage.start_char))
    expanded: list[RetrievedCandidate] = []
    seen: set[tuple[int, int]] = set()
    source_order = sorted(passages, key=lambda item: item.start_char)
    positions = {item.passage_id: i for i, item in enumerate(source_order)}
    import hashlib

    for candidate in candidates:
        core = candidate.passage
        pos = positions[core.passage_id]
        neighbors = [core]
        for other_pos in (pos - 1, pos + 1):
            if 0 <= other_pos < len(source_order):
                other = source_order[other_pos]
                # Keep headings/paragraph separators verbatim. Never jump a large gap.
                gap = max(other.start_char - core.end_char, core.start_char - other.end_char, 0)
                if len(other.text) <= 500 and gap <= 200:
                    neighbors.append(other)
        start = min(item.start_char for item in neighbors)
        end = max(item.end_char for item in neighbors)
        if (start, end) in seen:
            continue
        seen.add((start, end))
        content = source_text[start:end]
        digest = hashlib.sha256(content.encode()).hexdigest()
        passage = core.model_copy(
            update={
                "text": content,
                "start_char": start,
                "end_char": end,
                "sha256": digest,
                "passage_id": f"p-{start}-{end}-{digest[:12]}",
                "locator": f"{core.locator} / context-chars:{start}-{end}",
                "block_ids": list(dict.fromkeys(b for item in neighbors for b in item.block_ids)),
            }
        )
        expanded.append(
            RetrievedCandidate(passage=passage, score=candidate.score, rank=len(expanded) + 1)
        )
        if len(expanded) >= top_k:
            break
    return expanded
