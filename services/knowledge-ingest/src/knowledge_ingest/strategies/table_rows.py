# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`table_rows`: one `row` chunk per table row, with columns used by role (spec 14.4 to 14.6).

| Role | In `text` | In `indexed_text` | In `metadata` |
|---|---|---|---|
| searchable | yes | yes | no (the key column also as `row_key`) |
| metadata | yes | no | yes, under its snake_case name |
| ignored | no | no | no |

Columns the settings do not name are searchable. With no key column, the first searchable column is
the key. The key column is always searchable, so a row can be found by the value that names it.
"""

from __future__ import annotations

import re

from knowledge_ingest.models import Chunk, ColumnRole, Section, Table, TableColumn
from knowledge_ingest.strategies.base import SplitContext
from knowledge_ingest.text import snake_case

_BAND_HEADER = re.compile(r"band|amount|range", re.IGNORECASE)
_NUMBER = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?"


def _num(digits: str, suffix: str | None) -> float:
    value = float(digits.replace(",", ""))
    if suffix:
        value *= 1_000 if suffix.lower() == "k" else 1_000_000
    return value


def parse_band(value: str) -> tuple[float, float | None] | None:
    """`<= $250,000` → (0, 250000); `$250,001 - $500,000` → (250001, 500000); `500k+` → (500000, None)."""
    v = value.strip()
    if m := re.fullmatch(rf"(?:<=|\u2264|up to|under|below|<)\s*{_NUMBER}", v, re.IGNORECASE):
        return (0.0, _num(m.group(1), m.group(2)))
    if m := re.fullmatch(rf"(?:>=|\u2265|over|above|>|from)\s*{_NUMBER}", v, re.IGNORECASE):
        return (_num(m.group(1), m.group(2)), None)
    if m := re.fullmatch(rf"{_NUMBER}\s*(?:\+|and above|or more)", v, re.IGNORECASE):
        return (_num(m.group(1), m.group(2)), None)
    if m := re.fullmatch(rf"{_NUMBER}\s*(?:-|\u2013|to)\s*{_NUMBER}", v, re.IGNORECASE):
        return (_num(m.group(1), m.group(2)), _num(m.group(3), m.group(4)))
    if m := re.fullmatch(_NUMBER, v):
        n = _num(m.group(1), m.group(2))
        return (n, n)
    return None


def resolve_columns(headers: list[str], configured: list[TableColumn]) -> tuple[dict[str, ColumnRole], str | None]:
    """Return each header's role and the key header."""
    by_name = {c.name.strip().lower(): c for c in configured}
    roles: dict[str, ColumnRole] = {}
    key: str | None = None
    for header in headers:
        column = by_name.get(header.strip().lower())
        role: ColumnRole = column.role if column else "searchable"
        if column and column.key:
            role = "searchable"
            key = header
        roles[header] = role
    if key is None:
        key = next((h for h in headers if roles[h] == "searchable"), None)
    return roles, key


def split_table(table: Table, section: Section, ctx: SplitContext) -> list[Chunk]:
    roles, key = resolve_columns(table.headers, ctx.settings.columns)
    known = {h.strip().lower() for h in table.headers}
    for column in ctx.settings.columns:
        if column.name.strip().lower() not in known:
            ctx.notes.append(f"Column {column.name} is not in the table; its role was not applied.")

    chunks: list[Chunk] = []
    for row in table.rows:
        cells = dict(zip(table.headers, row + [""] * (len(table.headers) - len(row)), strict=False))
        text_lines = [f"{h}: {cells[h]}" for h in table.headers if roles[h] != "ignored" and cells[h]]
        indexed_lines = [f"{h}: {cells[h]}" for h in table.headers if roles[h] == "searchable" and cells[h]]
        metadata = {snake_case(h): cells[h] for h in table.headers if roles[h] == "metadata" and cells[h]}
        if key is not None:
            metadata["row_key"] = cells[key]
        if table.caption:
            metadata["table_caption"] = table.caption
        if table.sheet:
            metadata["sheet"] = table.sheet

        band: tuple[float, float | None] | None = None
        for header in table.headers:
            if roles[header] == "searchable" and _BAND_HEADER.search(header) and cells[header]:
                band = parse_band(cells[header])
                if band is None:
                    ctx.notes.append(f"Band {cells[header]!r} in column {header} did not parse and is stored as text.")
                break

        text = "\n".join(text_lines)
        if not text:
            continue
        chunks.append(
            Chunk(
                index=0,
                kind="row",
                text=text,
                indexed_text="\n".join(indexed_lines),
                section_path=list(section.heading_path),
                metadata=metadata,
                page=table.page,
                row_band=band,
            )
        )
    return chunks
