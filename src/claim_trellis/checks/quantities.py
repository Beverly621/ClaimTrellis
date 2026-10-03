import re

from claim_trellis.deterministic import normalize_text
from claim_trellis.models import CheckFinding

RANGE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:-|to)\s*\d+(?:\.\d+)?\s*\w*")


def ranges_check(claim: str, evidence: str) -> CheckFinding:
    ranges = RANGE_RE.findall(normalize_text(claim))
    source_ranges = RANGE_RE.findall(normalize_text(evidence))
    if not ranges and not source_ranges:
        return CheckFinding(
            check_id="quantities.ranges", status="not_applicable", reason="No explicit range."
        )
    # Conservative: being inside a range is never exact equality. Unit/range semantics
    # must be reviewed unless the same explicit range is present on both sides.
    equal = bool(ranges) and {re.sub(r"\s+", "", r) for r in ranges} <= {
        re.sub(r"\s+", "", r) for r in source_ranges
    }
    return CheckFinding(
        check_id="quantities.ranges",
        status="passed" if equal else "review_required",
        reason="Explicit range preserved."
        if equal
        else "Range and scalar quantities are not automatically equivalent; inspect their scope.",
        blocking=not equal,
    )
