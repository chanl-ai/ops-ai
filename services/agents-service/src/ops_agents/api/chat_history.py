"""A stored message as the next turn reads it: the text, and for a reply the skills it loaded and a line for each read
it made, so a follow-up keeps the skill and answers from the records already read instead of loading and reading again.
"""

from __future__ import annotations

import json
from typing import Any

from ops_contracts.chat import ChatMessage

# The kernel's own tools: presenting, loading a skill and searching are not reads of a system.
KERNEL_TOOLS = frozenset({"present", "load_skill", "search_tools", "search_knowledge"})
# A read's line is cut here: enough for the ids and names a follow-up needs, never a whole result set.
READ_CHARS = 700


def read_line(name: str, given: dict[str, Any], output: Any) -> str:
    line = f"{name} {json.dumps(given, ensure_ascii=False)} answered {json.dumps(output, ensure_ascii=False)}"
    return line if len(line) <= READ_CHARS else line[: READ_CHARS - 1] + "…"


def history_entry(m: ChatMessage) -> dict[str, Any]:
    entry: dict[str, Any] = {"role": m.role, "content": m.content}
    if m.role != "assistant":
        return entry
    if m.skills:
        entry["skills"] = [
            {"skillId": s.skill_id, "version": s.version, "name": s.name, "matched": s.matched} for s in m.skills
        ]
    reads = [
        read_line(c.name, c.input, c.output)
        for c in m.tool_calls or []
        if c.status == "success" and c.name not in KERNEL_TOOLS and c.output is not None
    ]
    if reads:
        entry["reads"] = reads
    return entry
