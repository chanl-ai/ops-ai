"""The one rule for a name or title a person types (an agent, guardrail, skill, form or link), and the one slug maker.

A name is NFKC-normalised, trimmed, on one line (a line break is refused; a tab or a run of spaces becomes one space),
never blank or made only of invisible characters, holds no control character, and is no longer than the column that
stores it. A request model uses `Name`, `Name80` or `Name120` so a bad name answers 400 in the house error shape; code
that checks a name by hand calls `name_problem` so every route gives the same message. A slug made from a name comes
from `slugify`. The console mirrors these rules in `apps/console/src/lib/validation/names.ts`."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated, LiteralString

from pydantic import BeforeValidator, Field
from pydantic_core import PydanticCustomError

# Room for "-" and up to four digits, which `_unique_slug` appends when a slug is taken.
SLUG_SUFFIX = 5
# Characters that end a line: LF, VT, FF, CR, NEL and the Unicode line and paragraph separators.
_LINE_BREAKS = re.compile(r"[\n\x0b\x0c\r\x85\u2028\u2029]")
# Categories a reader cannot see: format (zero-width space, bidi marks), separators, and unassigned or private use.
_INVISIBLE = {"Cc", "Cf", "Cn", "Co", "Cs", "Zs", "Zl", "Zp"}

Problem = tuple[LiteralString, LiteralString]
BLANK: Problem = ("name_blank", "The name cannot be blank.")
LINE_BREAK: Problem = ("name_line_break", "The name must be on one line; remove the line break.")
CONTROL: Problem = ("name_control", "The name cannot hold a control character.")


def has_control(name: str) -> bool:
    """True when `name` holds a control character (NUL, an escape)."""
    return any(unicodedata.category(c) == "Cc" for c in name)


def tidy(name: str) -> str:
    """`name` NFKC-normalised, each run of spaces or tabs made one space, then trimmed. Line breaks are left in place
    so `name_problem` can refuse them."""
    return re.sub(r"[ \t\u00a0\u3000]+", " ", unicodedata.normalize("NFKC", name)).strip()


def name_problem(name: str) -> Problem | None:
    """The (code, message) a tidied name is refused with, or None when it may be saved."""
    if not name or all(unicodedata.category(c) in _INVISIBLE for c in name):
        return BLANK
    if _LINE_BREAKS.search(name):
        return LINE_BREAK
    if has_control(name):
        return CONTROL
    return None


def clean_name(value: object) -> object:
    """The name as `tidy` leaves it; refused with `name_problem`'s code and message."""
    if not isinstance(value, str):
        return value
    name = tidy(value)
    problem = name_problem(name)
    if problem:
        raise PydanticCustomError(*problem)
    return name


# A name stored in a 200-wide column (agent, guardrail, skill, form title) and one in a 120-wide column (an MCP link).
Name = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=200)]
Name120 = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=120)]
Name80 = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=80)]
# A file name is capped but not checked for control characters: files-service sanitises it before it keeps the bytes.
FileName = Annotated[str, Field(min_length=1, max_length=255)]


def cap_slug(slug: str, width: int, *, reserve: int = 0, sep: str = "-") -> str:
    """`slug` cut to `width` less `reserve`, with no `sep` left dangling at the cut."""
    return slug[: width - reserve].rstrip(sep)


def name_hash(text: str) -> str:
    """8 hex characters of 32-bit FNV-1a over the lower-cased UTF-8 name; the console computes the same value."""
    h = 0x811C9DC5
    for b in text.lower().encode():
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def _untranslated(text: str) -> bool:
    """True when a letter or digit of `text` has no ASCII spelling (Chinese, Arabic, Cyrillic), so the ASCII slug
    alone would lose it."""
    return any(c.isalnum() and not unicodedata.normalize("NFKD", c).encode("ascii", "ignore") for c in text)


def slugify(name: str, *, width: int = 120, fallback: str = "", sep: str = "-", reserve: int = 0) -> str:
    """The one slug maker. Latin letters keep their base letter (`Zürich` gives `zurich`); when a letter has no ASCII
    spelling, an 8-character hash of the whole name is appended, so two names that differ only in non-Latin letters
    get distinct slugs and the same name always gets the same one. Empty input gives `fallback`. The result fits
    `width` less `reserve`, the room a caller keeps for a uniqueness suffix."""
    text = unicodedata.normalize("NFKC", name)
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", sep, ascii_text).strip(sep) if sep else re.sub(r"[^a-z0-9]+", "", ascii_text)
    tail = ""
    if _untranslated(text):
        tail = name_hash(text)
        base = base or fallback
    elif not base:
        return fallback
    room = width - reserve - (len(tail) + len(sep) if tail else 0)
    base = cap_slug(base, room, sep=sep) if sep else base[:room]
    return f"{base}{sep}{tail}" if tail and base else (tail or base)
