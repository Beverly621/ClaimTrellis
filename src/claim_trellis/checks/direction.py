import re

from claim_trellis.models import CheckFinding


def _directions(text: str) -> set[str]:
    words = text.lower()
    found: set[str] = set()
    for key, pattern in {
        "increase": r"\b(increas\w*|higher|rose)\b",
        "decrease": r"\b(decreas\w*|reduc\w*|lower|fell)\b",
        "null": r"\b(unchanged|no significant difference|no effect)\b",
    }.items():
        if re.search(pattern, words):
            found.add(key)
    return found


def direction_check(claim: str, evidence: str) -> CheckFinding:
    asserted, observed = _directions(claim), _directions(evidence)
    conflict = bool(asserted and observed and asserted.isdisjoint(observed))
    return CheckFinding(
        check_id="direction.lexical",
        status="review_required"
        if conflict
        else "not_applicable"
        if not asserted
        else "inconclusive",
        reason="Opposing lexical directions require contextual review."
        if conflict
        else "Lexical direction alone does not establish endpoint alignment.",
        blocking=conflict,
    )


def comparator_check(claim: str, evidence: str) -> CheckFinding:
    pattern = r"\b([\w-]+(?:\s+[A-Z])?)\s+(?:vs\.?|versus)\s+([\w-]+(?:\s+[A-Z])?)\b"
    asserted = re.findall(pattern, claim)
    missing = any(
        not all(re.search(r"\b" + re.escape(entity) + r"\b", evidence, re.I) for entity in pair)
        for pair in asserted
    )
    return CheckFinding(
        check_id="comparator.entities",
        status="review_required"
        if missing
        else "not_applicable"
        if not asserted
        else "inconclusive",
        reason="An explicit comparator entity is absent from selected evidence."
        if missing
        else "Comparator identity and comparison semantics require structured judgment.",
        blocking=missing,
    )
