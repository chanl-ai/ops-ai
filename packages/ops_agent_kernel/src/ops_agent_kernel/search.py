"""The built-in `search_tools` tool (c-062 T003): the model looks up, by words, the tools this turn already offers it,
the agent's own tool directory (granted registry operations and granted, published workflows), and gets each match's
name, description and input schema; it then calls the match by name. It finds nothing the turn does not offer, so it
never makes a tool callable, and it reaches no system.
"""

from __future__ import annotations

import re
from typing import Any

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


def search(tools: list[ToolGrant], query: str) -> list[dict[str, Any]]:
    """The offered tools sharing a word with `query`, most shared words first, at most LIMIT."""
    asked = _words(query)
    scored = [(len(asked & _words(f"{t.name} {t.description}")), t) for t in tools]
    hits = sorted((s for s in scored if s[0] > 0), key=lambda s: (-s[0], s[1].name))[:LIMIT]
    return [{"name": t.name, "description": t.description, "inputSchema": t.input_schema} for _, t in hits]
