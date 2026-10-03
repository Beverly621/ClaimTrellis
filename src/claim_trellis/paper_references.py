"""Bounded bibliography and citation-key heuristics; never establishes source identity."""

from __future__ import annotations

import hashlib
import re

from claim_trellis.paper_extraction import REFERENCE_HEADING
from claim_trellis.paper_models import ExactSpan, Manuscript, ReferenceEntry
from claim_trellis.paper_store import stable_id

REFERENCE_VERSION = "bibliography-exact-span-v1"
_NUMBER = re.compile(r"^\s*(?:\[(\d{1,4})\]|(\d{1,4})[.)])\s+")
_YEAR = re.compile(r"\b((?:19|20)\d{2})([a-z]?)\b")
_AUTHOR = re.compile(
    r"^\s*([A-Z][A-Za-z'’-]+)(?:,\s*(?:[A-Z]\.\s*)+|\s+(?:et al\.\s*)?\(?((?:19|20)\d{2}))"
)
_DOI = re.compile(r"\b10\.\d{4,9}/[^\s<>\"]+", re.I)


def normalized_doi(doi: str | None) -> str | None:
    match = _DOI.search(doi or "")
    return match.group().rstrip(".,;)").casefold() if match else None


def normalized_title(title: str | None) -> str | None:
    words = re.findall(r"\w+", (title or "").casefold())
    # Short titles are too ambiguous even for suggestions.
    return " ".join(words) if len(words) >= 3 else None


def marker_keys(marker: str) -> set[str]:
    value = marker.strip()
    numeric = value.strip("[]()")
    if re.fullmatch(r"\d{1,4}(?:\s*[-–—,]\s*\d{1,4})*", numeric):
        keys: set[str] = set()
        for group in numeric.split(","):
            numbers = re.split(r"[-–—]", group)
            first, last = int(numbers[0]), int(numbers[-1])
            if last < first or last - first > 199 or len(keys) + last - first + 1 > 200:
                return set()
            keys.update(f"n:{number}" for number in range(first, last + 1))
        return keys
    keys = set()
    for group in value.strip("()").split(";"):
        author = re.search(r"[A-Z][A-Za-z'’-]+", group)
        year = _YEAR.search(group)
        if author and year:
            keys.add(f"a:{author.group().casefold()}:{year[1]}{year[2]}")
    return keys


def parse_references(manuscript: Manuscript) -> list[ReferenceEntry]:
    heading = REFERENCE_HEADING.search(manuscript.text)
    if not heading:
        return []  # No undocumented guess about where the bibliography starts.
    end = len(manuscript.text)
    section = re.search(
        r"(?im)^\s*(?:#{1,6}\s+.+|appendix\b[^\n]*|supplementary (?:material|information)[^\n]*)$",
        manuscript.text[heading.end() :],
    )
    if section:
        end = heading.end() + section.start()
    starts: list[tuple[int, str]] = []
    cursor = heading.end()
    for line in manuscript.text[cursor:end].splitlines(keepends=True):
        number, author, year = _NUMBER.match(line), _AUTHOR.match(line), _YEAR.search(line[:300])
        if number:
            starts.append(
                (cursor + len(line) - len(line.lstrip()), f"[{int(number[1] or number[2])}]")
            )
        elif author and year:
            starts.append(
                (cursor + len(line) - len(line.lstrip()), f"({author[1]}, {year[1]}{year[2]})")
            )
        cursor += len(line)
    if len(starts) > 2000:
        raise ValueError("More than 2,000 bibliography entries; split the manuscript.")
    result = []
    for index, (start, marker) in enumerate(starts):
        stop = starts[index + 1][0] if index + 1 < len(starts) else end
        while stop > start and manuscript.text[stop - 1].isspace():
            stop -= 1
        raw = manuscript.text[start:stop]
        year = _YEAR.search(raw)
        # APA-like year-first entries only. Other layouts keep title unknown for manual mapping.
        title = None
        if year and year.start() < 300:
            remainder = raw[year.end() :].lstrip("). ;:\n")
            tentative = re.split(r"\.\s+(?=[A-Z])|\n\s*\n", remainder, maxsplit=1)[0]
            if normalized_title(tentative) and not _DOI.search(tentative):
                title = tentative.strip().rstrip(".")
        author = re.search(r"[A-Z][A-Za-z'’-]+", _NUMBER.sub("", raw))
        result.append(
            ReferenceEntry(
                reference_id=stable_id(
                    manuscript.manuscript_id,
                    f"{REFERENCE_VERSION}:{manuscript.content_sha256}:{start}:{stop}",
                ),
                project_id=manuscript.project_id,
                manuscript_id=manuscript.manuscript_id,
                manuscript_locator=f"chars:{start}-{stop}",
                span=ExactSpan(start=start, end=stop),
                raw_reference=raw,
                markers=[marker],
                title=title,
                authors=[author.group()] if author else [],
                year=int(year[1]) if year else None,
                doi=normalized_doi(raw),
                sha256=hashlib.sha256(raw.encode()).hexdigest(),
                parser_version=REFERENCE_VERSION,
            )
        )
    return result
