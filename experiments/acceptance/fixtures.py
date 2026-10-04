"""Invented fixtures under the repository license, not real papers or scientific labels."""

from experiments.retrieval.fixtures import CASES

CLAIM = CASES[0][0]
EDITED_CLAIM = "In adults, intervention A reduced systolic blood pressure."


def manuscript(style: str) -> str:
    markers = (
        ["[1, 2]", "[1]", "[2]", "[3]"]
        if style == "numeric"
        else ["(Smith, 2024; Jones, 2025)", "(Smith, 2024)", "(Jones, 2025)", "(Lee, 2026)"]
    )
    claims = [CLAIM, CASES[4][0], CASES[2][0], CASES[5][0]]
    body = "\n\n".join(
        f"{c.rstrip('.')} {marker}." for c, marker in zip(claims, markers, strict=True)
    )
    refs = [
        "Smith, J. (2024). Fictional blood pressure study. Synthetic Fixtures. doi:10.1234/fictional-a.",
        "Jones, A. (2025). Fictional replication study. Synthetic Fixtures. doi:10.1234/fictional-b.",
        "Lee, L. (2026). Fictional mobility study. Synthetic Fixtures. doi:10.1234/fictional-unmapped.",
    ]
    if style == "numeric":
        refs = [f"[{i}] {r}" for i, r in enumerate(refs, 1)]
    return (
        "Synthetic acceptance manuscript: invented software fixture.\n\n"
        + body
        + "\n\nReferences\n"
        + "\n".join(refs)
    )


def source_text() -> str:
    context = (
        " This invented source exercises exact-span retrieval and reviewer persistence, not scientific validation."
        " It has fictional participants and results, no clinical records, and no publisher material."
        " Distinct paragraphs retain their original boundaries and do not become synthetic adjacent evidence."
        " The remaining context documents the artificial study protocol and the fixture identity."
        " The laboratory operators recorded named endpoints and outcome directions separately."
        " No findings in this fixture describe a real scientific study or establish a clinical recommendation."
    )
    return "\n\n".join(c + context for c in [CLAIM, CASES[4][0], CASES[0][1], CASES[5][0]])
