from claim_trellis.deterministic import _equivalent, extract_numeric_tokens
from claim_trellis.models import CheckFinding


def numbers_check(claim: str, evidence: str) -> CheckFinding:
    values = extract_numeric_tokens(claim)
    source = extract_numeric_tokens(evidence)
    missing = [
        token.raw for token in values if not any(_equivalent(token, other) for other in source)
    ]
    return CheckFinding(
        check_id="numbers.quantities",
        status="not_applicable" if not values else "review_required" if missing else "passed",
        reason="No numeric quantity asserted."
        if not values
        else "Unmatched quantities: " + ", ".join(missing)
        if missing
        else "Values and explicit units match; occurrence alone does not prove semantic identity.",
        blocking=bool(missing),
    )
