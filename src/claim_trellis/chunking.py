from __future__ import annotations

import hashlib
import re

from claim_trellis.citations import sentence_spans
from claim_trellis.models import EvidencePassage

RETRIEVAL_VERSION = "lexical-evidence-v2"


def _passage(text: str, start: int, end: int, index: int) -> EvidencePassage:
    content = text[start:end].strip()
    left_trim = len(text[start:end]) - len(text[start:end].lstrip())
    right_trim = len(text[start:end]) - len(text[start:end].rstrip())
    real_start = start + left_trim
    real_end = end - right_trim
    digest = hashlib.sha256(content.encode()).hexdigest()
    return EvidencePassage(
        passage_id=f"p-{index:05d}-{digest[:12]}",
        text=content,
        locator=f"chars:{real_start}-{real_end}",
        start_char=real_start,
        end_char=real_end,
        sha256=digest,
    )


def chunk_text(
    text: str,
    *,
    target_chars: int = 1_500,
    max_chars: int = 2_400,
    overlap_sentences: int = 1,
) -> list[EvidencePassage]:
    """Create stable sentence-aligned passages with small semantic overlap."""

    spans = sentence_spans(text)
    if not spans:
        return []

    passages: list[EvidencePassage] = []
    cursor = 0
    index = 1
    while cursor < len(spans):
        start = spans[cursor][0]
        end_cursor = cursor
        end = spans[end_cursor][1]
        while end_cursor + 1 < len(spans):
            next_end = spans[end_cursor + 1][1]
            if next_end - start > max_chars:
                break
            end_cursor += 1
            end = next_end
            if end - start >= target_chars and re.search(r"\n\s*\n", text[start:end]):
                break
        passages.append(_passage(text, start, end, index))
        index += 1
        if end_cursor == len(spans) - 1:
            break
        cursor = max(cursor + 1, end_cursor + 1 - overlap_sentences)
    return passages
