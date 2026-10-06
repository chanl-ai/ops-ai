# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Plain text and Markdown. ATX headings (`#`) open sections and pipe tables become tables."""

from __future__ import annotations

import re

from knowledge_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata
from knowledge_ingest.parsers.builder import DocumentBuilder

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_TABLE_RULE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_text(
    data: bytes,
    *,
    filename: str,
    mime_type: str = "text/plain",
    parsing: ParsingSettings | None = None,
    fields: dict[str, str] | None = None,
) -> ParsedDocument:
    parsing = parsing or ParsingSettings()
    text = decode(data).replace("\r\n", "\n")
    markdown = mime_type == "text/markdown" or filename.lower().endswith((".md", ".markdown"))
    builder = DocumentBuilder()
    lines = text.split("\n")
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            builder.paragraph(" ".join(paragraph))
            paragraph.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        heading = _HEADING.match(line) if markdown else None
        if heading:
            flush()
            builder.heading(heading.group(2), len(heading.group(1)))
        elif markdown and "|" in line and i + 1 < len(lines) and _TABLE_RULE.match(lines[i + 1].strip()):
            flush()
            headers = _cells(line)
            rows: list[list[str]] = []
            i += 2
            while i < len(lines) and "|" in lines[i]:
                rows.append(_cells(lines[i]))
                i += 1
            builder.table(headers, rows, keep_as_table=parsing.tables)
            continue
        elif not line.strip():
            flush()
        else:
            paragraph.append(line.strip())
        i += 1
    flush()

    source = SourceMetadata(
        filename=filename,
        mime_type="text/markdown" if markdown else mime_type,
        size_bytes=len(data),
        fields=fields or {},
    )
    return builder.build(title=None, source=source)
