from claim_trellis.models import CheckFinding


def citation_check(citation: str | None) -> CheckFinding:
    return CheckFinding(
        check_id="citation.identity",
        status="human_required",
        reason="Confirm the supplied citation identifies this source."
        if citation
        else "No citation identifier supplied; source identity must be confirmed by the reviewer.",
    )
