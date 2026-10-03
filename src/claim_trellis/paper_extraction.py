"""Conservative clause suggestions copied exclusively from exact manuscript spans."""

from __future__ import annotations

import hashlib
import re

from claim_trellis.citations import citation_markers, extract_citation_sentences
from claim_trellis.paper_models import ClaimCandidate, ExactSpan, Manuscript
from claim_trellis.paper_store import stable_id

EXTRACTION_VERSION = "citation-exact-span-v1"
REFERENCE_HEADING = re.compile(r"(?im)^\s*(?:#{1,6}\s*)?(?:references|bibliography)\s*:?\s*$")
# Deliberately small vocabulary: unknown structures stay intact for a human to edit.
_VERB = r"(?:improves?|reduces?|increases?|decreases?|achieves?|outperforms?|shows?|demonstrates?|produces?|requires?|supports?|fails?|is|are|was|were|has|have|can|may|does|do)\b"
_COORDINATE = re.compile(r"\s+(?:and|but|whereas)\s+(?=" + _VERB + r")", re.I)


def body_end(text: str) -> int:
    heading = REFERENCE_HEADING.search(text)
    return heading.start() if heading else len(text)


def clause_spans(sentence: str) -> list[tuple[int, int]]:
    """Split top-level semicolons and obvious coordinated predicates, never noun lists."""
    cuts = {match.start(): match.end() for match in _COORDINATE.finditer(sentence)}
    cuts.update({match.start(): match.end() for match in re.finditer(r";\s*", sentence)})
    spans, start, depth, quote = [], 0, 0, False
    for index, char in enumerate(sentence):
        if char in '"“”':
            quote = not quote
        if not quote:
            if char in "([":
                depth += 1
            elif char in ")]":
                depth = max(depth - 1, 0)
        if index in cuts and depth == 0 and not quote:
            spans.append((start, index))
            start = cuts[index]
    spans.append((start, len(sentence)))
    grounded = []
    for left, right in spans:
        while left < right and sentence[left].isspace():
            left += 1
        while right > left and sentence[right - 1] in " \t\r\n.;":
            right -= 1
        # Remove only terminal/leading citation markers by changing boundaries.
        for marker in reversed(citation_markers(sentence[left:right])):
            if marker.startswith(("[", "(")) and sentence[left:right].endswith(marker):
                right -= len(marker)
                while right > left and sentence[right - 1].isspace():
                    right -= 1
        for marker in citation_markers(sentence[left:right]):
            if marker.startswith(("[", "(")) and sentence[left:right].startswith(marker):
                left += len(marker)
                while left < right and sentence[left].isspace():
                    left += 1
        if right - left >= 3 and re.search(r"[A-Za-z]", sentence[left:right]):
            grounded.append((left, right))
    return grounded


def extract_candidates(manuscript: Manuscript) -> list[ClaimCandidate]:
    candidates = []
    for sentence in extract_citation_sentences(manuscript.text[: body_end(manuscript.text)]):
        parts = clause_spans(sentence.sentence)
        for start, end in parts:
            start += sentence.start_char
            end += sentence.start_char
            original = manuscript.text[start:end]
            markers = citation_markers(original) or sentence.markers
            warnings = ["Human atomicity, faithfulness and necessary-context review required."]
            if len(parts) > 1:
                warnings.append(
                    "Clause may omit its subject/context; citation scope needs human review."
                )
            candidates.append(
                ClaimCandidate(
                    candidate_id=stable_id(
                        manuscript.manuscript_id,
                        f"{EXTRACTION_VERSION}:{manuscript.content_sha256}:{start}:{end}",
                    ),
                    project_id=manuscript.project_id,
                    manuscript_id=manuscript.manuscript_id,
                    source_sentence=sentence.sentence,
                    sentence_span=ExactSpan(start=sentence.start_char, end=sentence.end_char),
                    exact_span_start=start,
                    exact_span_end=end,
                    original_span=original,
                    citation_markers=markers,
                    suggested_clause_span=ExactSpan(start=start, end=end),
                    extraction_version=EXTRACTION_VERSION,
                    sha256=hashlib.sha256(original.encode()).hexdigest(),
                    extraction_warnings=warnings,
                )
            )
            if len(candidates) > 2000:
                raise ValueError(
                    "More than 2,000 candidates; split the manuscript before extraction."
                )
    return candidates
