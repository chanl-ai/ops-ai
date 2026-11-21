"""The one rule for a name a person types (an agent, guardrail, skill, form or link): on one line, trimmed, never
blank, no control characters, and no longer than the column that stores it. A request model uses `Name` or `Name120`
so a bad name answers 400 in the house error shape; a slug made from a name goes through `cap_slug` so it fits its
column with the numeric suffix a uniqueness check may add."""

from __future__ import annotations

import re
import unicodedata
from typing import Annotated

from pydantic import BeforeValidator, Field
from pydantic_core import PydanticCustomError

# Room for "-" and up to four digits, which `_unique_slug` appends when a slug is taken.
SLUG_SUFFIX = 5


def has_control(name: str) -> bool:
    """True when `name` holds a control character (NUL, an escape); `tidy` has already made line breaks spaces."""
    return any(unicodedata.category(c) == "Cc" for c in name)


def tidy(name: str) -> str:
    """`name` on one line: each run of whitespace (a space, tab, CR or LF) becomes one space, then it is trimmed. A
    name saved with a line break before this rule re-saves unchanged instead of failing."""
    return re.sub(r"\s+", " ", name).strip()


def clean_name(value: object) -> object:
    """The name as `tidy` leaves it; a blank one, or one still holding a control character (NUL), is refused."""
    if not isinstance(value, str):
        return value
    name = tidy(value)
    if not name:
        raise PydanticCustomError("name_blank", "The name cannot be blank.")
    if has_control(name):
        raise PydanticCustomError("name_control", "The name cannot hold a control character.")
    return name


# A name stored in a 200-wide column (agent, guardrail, skill, form title) and one in a 120-wide column (an MCP link).
Name = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=200)]
Name120 = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=120)]
Name80 = Annotated[str, BeforeValidator(clean_name), Field(min_length=1, max_length=80)]
# A file name is capped but not checked for control characters: files-service sanitises it before it keeps the bytes.
FileName = Annotated[str, Field(min_length=1, max_length=255)]


def cap_slug(slug: str, width: int, *, reserve: int = 0, sep: str = "-") -> str:
    """The one cutter of a slug made from a name: `slug` cut to `width` less `reserve`, with no `sep` left dangling at
    the cut."""
    return slug[: width - reserve].rstrip(sep)
