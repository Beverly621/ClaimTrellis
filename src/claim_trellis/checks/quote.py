from claim_trellis.deterministic import locate_quote
from claim_trellis.models import CheckFinding


def quote_check(evidence: str, quote: str | None) -> CheckFinding:
    found = quote is None or locate_quote(evidence, quote)[0]
    return CheckFinding(
        check_id="quote.selected_context",
        status="not_applicable" if quote is None else "passed" if found else "review_required",
        reason="Quote not requested."
        if quote is None
        else "Quote found in selected evidence."
        if found
        else "Requested quote is absent from the evidence sent to the provider.",
        blocking=not found,
    )
