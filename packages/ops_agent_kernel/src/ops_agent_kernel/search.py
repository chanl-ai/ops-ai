"""Finding tools by words (c-062 T003, c-610). Below the agent's tool-search threshold, the built-in `search_tools`
looks up the tools this turn already offers (the agent's granted registry operations and granted, published workflows)
and returns each match's name, description and input schema. Above it, every granted tool is deferred and
pydantic-ai's own tool search finds them with `strategy`, the same word scoring: a found tool is revealed and then
called by its own name, through the same call path as any other. Either way it finds nothing the agent is not granted
and reaches no system.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.tools import ToolDefinition

from .types import ToolGrant

NAME = "search_tools"
SERVER = "kernel"
LIMIT = 10
_WORD = re.compile(r"[a-z0-9]+")

SEARCH = ToolGrant(
    NAME,
    SERVER,
    "Find the tools and workflows you can use, by words from their name or description. Returns each match's name, "
    "description and input schema; call a match by its name. Reads nothing and changes nothing.",
    "read",
    {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Words to look for, e.g. 'refund dispute'"}},
        "required": ["query"],
    },
)


def _words(text: str) -> set[str]:
    return set(_WORD.findall(text.lower().replace("_", " ")))


# What the search tool says while the agent's tools are deferred: the model knows its tools are not listed.
DEFERRED = (
    "Your tools are not listed until you find them. Search by words from what you need, e.g. 'refund dispute'; each "
    "match becomes callable by its own name on your next step. Reads nothing and changes nothing."
)


def _ranked(entries: Sequence[tuple[str, str]], query: str) -> list[str]:
    """Names of `entries` (name, description) sharing a word with `query`, most shared words first, at most LIMIT."""
    asked = _words(query)
    scored = [(len(asked & _words(f"{name} {description}")), name) for name, description in entries]
    return [name for _, name in sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1]))[:LIMIT]]


def search(tools: list[ToolGrant], query: str) -> list[dict[str, Any]]:
    """The offered tools sharing a word with `query`, most shared words first, at most LIMIT."""
    by_name = {t.name: t for t in tools}
    hits = [by_name[n] for n in _ranked([(t.name, t.description) for t in tools], query)]
    return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for t in hits]


def strategy(_ctx: RunContext[Any], queries: Sequence[str], tools: Sequence[ToolDefinition]) -> list[str]:
    """pydantic-ai's tool search strategy over the deferred tools, with the same scoring as `search`."""
    return _ranked([(t.name, t.description or "") for t in tools], " ".join(queries))
