# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`clean`: remove leftover markup and boilerplate lines before splitting.

HTML furniture (navigation, banners, footers) is removed by the HTML parser when `clean` is on; this
pass covers text from any format, such as a cookie notice pasted into a DOCX. Spec 1.6 takes the
content digest after `clean`, so a change to page furniture alone does not create a new version.
"""

from __future__ import annotations

import re

from knowledge_ingest.models import Block, Paragraph, ParsedDocument, Section

_TAG = re.compile(r"<[^>]{1,200}>")
_BOILERPLATE = re.compile(
    r"^(skip to (main )?content|back to top|share (this|on)\b|follow us\b|subscribe\b|"
    r"(©|copyright)\s|all rights reserved|we use cookies|this (web)?site uses cookies|accept( all)? cookies|"
    r"cookie (settings|preferences|policy))",
    re.IGNORECASE,
)


def clean_document(document: ParsedDocument) -> tuple[ParsedDocument, int]:
    """Return the cleaned document and the number of characters removed."""
    removed = 0
    sections: list[Section] = []
    for section in document.sections:
        blocks: list[Block] = []
        for block in section.blocks:
            if isinstance(block, Paragraph):
                stripped = " ".join(_TAG.sub(" ", block.text).split())
                if not stripped or _BOILERPLATE.match(stripped):
                    removed += len(block.text)
                    continue
                removed += len(block.text) - len(stripped)
                blocks.append(block.model_copy(update={"text": stripped}))
            else:
                blocks.append(block)
        sections.append(section.model_copy(update={"blocks": blocks}))
    return document.model_copy(update={"sections": sections}), removed
