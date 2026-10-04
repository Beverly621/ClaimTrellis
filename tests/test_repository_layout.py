"""Public documentation and asset invariants; private operational records are not fixtures."""

import re
import struct
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = {
    "ANNOTATION_GUIDE.md",
    "ARCHITECTURE.md",
    "DATA_MODEL.md",
    "DEPENDENCY_PROVENANCE.md",
    "EVALUATION_PROTOCOL.md",
    "LITERATURE_POLICY.md",
    "PAPER_WORKFLOW.md",
    "PRIVACY.md",
    "ROADMAP.md",
    "SELF_HOSTING.md",
    "THREAT_MODEL.md",
    "TRUST_SPEC.md",
}


def test_public_docs_and_local_links_are_complete():
    assert {path.name for path in (ROOT / "docs").iterdir()} == PUBLIC_DOCS
    documents = [
        *ROOT.glob("*.md"),
        *(ROOT / "docs").glob("*.md"),
        ROOT / "experiments/retrieval/README.md",
        ROOT / "benchmarks/retrieval/README.md",
    ]
    for document in documents:
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text()):
            if "://" in link or link.startswith("#") or "{{" in link:
                continue
            target = unquote(link.split("#", 1)[0])
            assert (document.parent / target).exists(), f"Broken link in {document.name}: {target}"
    assert not (ROOT / "benchmarks/retrieval/reports").exists()
    for name in ("private-workspace", "private", "internal"):
        assert not (ROOT / name).exists()


def test_approved_brand_assets_and_page_references():
    readme = (ROOT / "README.md").read_text()
    assert 'src="web/brand/lockup.png" alt="ClaimTrellis" width="430"' in readme
    assert "lockup.svg" not in readme
    for filename, expected in {
        "mark.png": (512, 512),
        "lockup.png": (923, 244),
        "favicon-32.png": (32, 32),
    }.items():
        content = (ROOT / "web/brand" / filename).read_bytes()
        assert content[:8] == b"\x89PNG\r\n\x1a\n"
        assert struct.unpack(">II", content[16:24]) == expected
    for filename in ("index.html", "history.html", "projects.html"):
        html = (ROOT / "web" / filename).read_text()
        assert "/assets/brand/lockup.png" in html
        assert "/assets/brand/favicon-32.png" in html
        assert "/assets/brand/mark.png" in html
        assert 'class="alpha"' not in html
        assert "/assets/mark.svg" not in html
        assert 'href="/docs"' not in html
