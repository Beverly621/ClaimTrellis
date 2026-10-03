from claim_trellis.models import CheckFinding


def completeness_check(evidence: str | None, access_tier: str) -> CheckFinding:
    return CheckFinding(
        check_id="source.completeness",
        status="review_required"
        if not evidence
        else "passed"
        if access_tier == "full_text"
        else "human_required",
        reason="No readable selected evidence."
        if not evidence
        else "Source scope: "
        + access_tier
        + "; supplied text is not proof of complete source coverage.",
        blocking=not bool(evidence),
    )
