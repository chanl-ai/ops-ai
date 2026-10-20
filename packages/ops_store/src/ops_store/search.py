"""Portable text search for store queries (data-and-portability.md, "A search escapes the wildcards"): the person's text
has `%`, `_` and the escape character escaped, the statement names the escape character (SQL Server has no default),
and both sides are lower-cased (PostgreSQL compares LIKE case-sensitively, SQL Server's usual collations do not).
SQL Server also reads `[` as the start of a character class, so it is escaped too."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa


def like_pattern(text: str) -> str:
    """`%text%` with the wildcards in `text` escaped, lower-cased."""
    escaped = text.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")
    return f"%{escaped}%"


def contains(column: sa.ColumnElement[Any], text: str) -> sa.ColumnElement[bool]:
    """`lower(column)` contains `text` as typed: `50%` matches only rows holding "50%", never every row."""
    return sa.func.lower(column).like(like_pattern(text), escape="\\")
