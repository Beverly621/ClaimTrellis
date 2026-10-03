from __future__ import annotations

import hashlib
import re
import unicodedata

from claim_trellis.models import DeterministicChecks, NumericToken

DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<number>-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|-?\.\d+)"
    r"\s*(?P<unit>%|percent(?:age)?\b|mg\b|g\b|kg\b|µg\b|μg\b|ml\b|l\b|mmhg\b|years?\b|months?\b|days?\b|hours?\b)?",
    re.IGNORECASE,
)


def normalize_text(text: str) -> str:
    text = re.sub(r"(?<=[A-Za-z])-\s*\n\s*(?=[a-z])", "", text)
    normalized = unicodedata.normalize("NFKC", text).translate(DASHES).translate(QUOTES)
    return re.sub(r"\s+", " ", normalized).strip().lower()


def text_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode()).hexdigest()


def locate_quote(source_text: str, quote: str) -> tuple[bool, int | None]:
    needle = normalize_text(quote)
    if not needle:
        return False, None
    index = normalize_text(source_text).find(needle)
    return index >= 0, index if index >= 0 else None


def extract_numeric_tokens(text: str) -> list[NumericToken]:
    tokens: list[NumericToken] = []
    for match in NUMBER_RE.finditer(normalize_text(text)):
        raw = match.group("number")
        value = float(raw.replace(",", ""))
        unit = match.group("unit")
        tokens.append(NumericToken(raw=match.group(0).strip(), normalized=value, unit=unit))
    return tokens


def _equivalent(left: NumericToken, right: NumericToken) -> bool:
    from decimal import Decimal

    aliases = {
        "percent": "%",
        "percentage": "%",
        "year": "years",
        "month": "months",
        "day": "days",
        "hour": "hours",
        "µg": "μg",
    }
    units = {
        "kg": ("mass", "1000"),
        "g": ("mass", "1"),
        "mg": ("mass", "0.001"),
        "μg": ("mass", "0.000001"),
        "l": ("volume", "1"),
        "ml": ("volume", "0.001"),
    }
    left_unit = aliases.get(left.unit or "", left.unit or "")
    right_unit = aliases.get(right.unit or "", right.unit or "")
    left_dimension, left_factor = units.get(left_unit, (left_unit, "1"))
    right_dimension, right_factor = units.get(right_unit, (right_unit, "1"))

    def exact_value(token: NumericToken) -> Decimal:
        match = NUMBER_RE.match(normalize_text(token.raw))
        # Legacy numeric tokens may lack their original spelling.
        return Decimal(match.group("number").replace(",", "") if match else str(token.normalized))

    return left_dimension == right_dimension and exact_value(left) * Decimal(
        left_factor
    ) == exact_value(right) * Decimal(right_factor)


def run_deterministic_checks(
    claim: str,
    evidence: str | None,
    quote: str | None = None,
    *,
    quote_source_text: str | None = None,
    citation: str | None = None,
    access_tier: str = "unknown",
) -> DeterministicChecks:
    claim_numbers = extract_numeric_tokens(claim)
    evidence_numbers = extract_numeric_tokens(evidence or "")
    unmatched = [
        token
        for token in claim_numbers
        if not any(_equivalent(token, candidate) for candidate in evidence_numbers)
    ]
    warnings: list[str] = []
    quote_found: bool | None = None
    if quote is not None:
        quote_found, _ = locate_quote(
            quote_source_text if quote_source_text is not None else evidence or "", quote
        )
        if not quote_found:
            warnings.append("The requested quote was not found in the selected evidence passage.")
    if unmatched:
        warnings.append(
            "One or more numeric values in the claim were not found in the selected passage."
        )
    if evidence is None:
        warnings.append("No evidence passage was retrieved.")
    from claim_trellis.checks import CHECK_SET_VERSION, run_registry

    findings = run_registry(claim, evidence, quote, citation, access_tier)
    warnings.extend(finding.reason for finding in findings if finding.blocking)
    return DeterministicChecks(
        normalized_claim_sha256=text_sha256(claim),
        selected_evidence_sha256=text_sha256(evidence) if evidence else None,
        quote_requested=quote is not None,
        quote_found=quote_found,
        claim_numbers=claim_numbers,
        evidence_numbers=evidence_numbers,
        unmatched_claim_numbers=unmatched,
        warnings=warnings,
        findings=findings,
        check_set_version=CHECK_SET_VERSION,
    )
