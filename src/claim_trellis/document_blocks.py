from __future__ import annotations

import hashlib
import re

from claim_trellis.models import DocumentBlock

PARSER_VERSION = "structured-document-v2"


def make_block(
    text: str,
    start: int,
    end: int,
    index: int,
    *,
    block_type: str = "paragraph",
    page: int | None = None,
    section: str | None = None,
    paragraph: int | None = None,
    locator: str | None = None,
) -> DocumentBlock:
    content = text[start:end]
    digest = hashlib.sha256(content.encode()).hexdigest()
    return DocumentBlock(
        block_id=f"b-{index:05d}-{digest[:12]}",
        block_type=block_type,
        text=content,
        char_start=start,
        char_end=end,
        sha256=digest,
        page=page,
        section=section,
        paragraph=paragraph,
        locator=locator or f"chars:{start}-{end}",
    )


def text_blocks(text: str, *, markdown: bool = False) -> list[DocumentBlock]:
    """Offsets and TXT line numbers refer to the unchanged normalized text."""
    blocks: list[DocumentBlock] = []
    headings: list[tuple[int, str]] = []
    for match in re.finditer(r"(?m)^#{1,6}\s[^\n]+|[^\n]+(?:\n(?!\s*\n|#{1,6}\s)[^\n]+)*", text):
        start, end = match.span()
        content = match.group()
        heading = re.match(r"^(#{1,6})\s+(.+)$", content) if markdown else None
        if heading:
            level = len(heading[1])
            headings = [(depth, title) for depth, title in headings if depth < level]
            headings.append((level, heading[2].strip()))
        section = " > ".join(title for _, title in headings) or None
        first_line = text.count("\n", 0, start) + 1
        last_line = text.count("\n", 0, end) + 1
        locator = (
            f"heading:{section or '(none)'} / block:{len(blocks) + 1}"
            if markdown
            else f"lines:{first_line}-{last_line}"
        )
        blocks.append(
            make_block(
                text,
                start,
                end,
                len(blocks) + 1,
                block_type="heading" if heading else "paragraph",
                section=section,
                paragraph=len(blocks) + 1,
                locator=locator,
            )
        )
    return blocks


def validate_blocks(text: str, blocks: list[DocumentBlock]) -> None:
    seen: set[str] = set()
    previous_end = 0
    for block in blocks:
        if (
            block.block_id in seen
            or block.char_start < previous_end
            or bool(text[previous_end : block.char_start].strip())
            or block.char_end <= block.char_start
            or block.char_end > len(text)
            or text[block.char_start : block.char_end] != block.text
            or hashlib.sha256(block.text.encode()).hexdigest() != block.sha256
        ):
            raise ValueError("Document blocks must be unique, ordered, source-grounded spans.")
        seen.add(block.block_id)
        previous_end = block.char_end
    if blocks and text[previous_end:].strip():
        raise ValueError("Document blocks must cover the normalized source text.")
