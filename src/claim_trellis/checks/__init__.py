from __future__ import annotations

from claim_trellis.checks.citation import citation_check
from claim_trellis.checks.completeness import completeness_check
from claim_trellis.checks.direction import comparator_check, direction_check
from claim_trellis.checks.numbers import numbers_check
from claim_trellis.checks.quantities import ranges_check
from claim_trellis.checks.quote import quote_check
from claim_trellis.models import CheckFinding

CHECK_SET_VERSION = "deterministic-v2"


def run_registry(
    claim: str, evidence: str | None, quote: str | None, citation: str | None, access_tier: str
) -> list[CheckFinding]:
    return [
        quote_check(evidence or "", quote),
        numbers_check(claim, evidence or ""),
        ranges_check(claim, evidence or ""),
        direction_check(claim, evidence or ""),
        comparator_check(claim, evidence or ""),
        citation_check(citation),
        completeness_check(evidence, access_tier),
    ]
