"""The one rule for a name a person types (an agent, guardrail, skill, form or link): trimmed, never blank, no control
characters, and no longer than the column that stores it. A request model uses `Name` or `Name120` so a bad name answers
400 in the house error shape; a slug made from a name goes through `cap_slug` so it fits its column with the numeric
suffix a uniqueness check may add."""

from __future__ import annotations

import unicodedata
from typing import Annotated

from pydantic import BeforeValidator, Field

# Room for "-" and up to four digits, which `_unique_slug` appends when a slug is taken.
SLUG_SUFFIX = 5


def has_control(name: str) -> bool:
    """True when `name` holds a control character: NUL, a line break or a tab."""
    return any(unicodedata.category(c) == "Cc" for c in name)


def clean_name(value: object) -> object:
    """The trimmed name; a blank one, or one holding a control character (NUL, a line break, a tab), is refused."""
    if not isinstance(value, str):
        return value
    name = value.strip()
    if not name:
        raise ValueError("The name cannot be blank.")
    if has_control(name):
        raise ValueError("The name cannot hold a control character or a line break.")
    return name


# A name stored in a 200-wide column (agent, guardrail, skill, form title) and one in a 120-wide column (an MCP link).
Name = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=200)]
Name120 = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=120)]


def cap_slug(slug: str, width: int, *, reserve: int = 0) -> str:
    """`slug` cut to `width` less `reserve`, with no hyphen left dangling at the cut."""
    return slug[: width - reserve].rstrip("-")
