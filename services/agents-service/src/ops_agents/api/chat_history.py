"""A stored message as the next turn reads it: the text, and for a reply the skills it loaded and a line for each read
it made, so a follow-up keeps the skill and answers from the records already read instead of loading and reading again.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from ops_agent_kernel.plan import from_part as plan_from_part
from ops_contracts.chat import ChatMessage

# The kernel's own tools: presenting, loading a skill and searching are not reads of a system.
KERNEL_TOOLS = frozenset({"present", "load_skill", "search_tools", "search_knowledge", "plan"})
# The id of a reply's plan part (chat_threads.PLAN_PART).
PLAN_PART = "wp_plan"
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
    drawn = next((p for p in m.parts or [] if p.id == PLAN_PART), None)
    if drawn is not None and (left := plan_from_part(drawn.wire())) is not None:
        entry["plan"] = left
    return entry


# History compaction: past COMPACT_AFTER messages, the oldest whole tens are summarised into one first message and the
# rest are sent as they are; the summary is kept on the thread and made again only when ten more messages pass.
COMPACT_AFTER = 20
COMPACT_STEP = 10
SUMMARY_LEAD = "Summary of the earlier conversation:"
SUMMARY_PROMPT = (
    "Summarise this conversation for the assistant that continues it: who asked what, what was found and decided, "
    "and what is still open, in at most 200 words of plain sentences. Keep names and figures; leave out ids, links "
    "and anything about how the tools were called."
)


async def compacted(
    history: list[dict[str, Any]],
    held: dict[str, Any] | None,
    summarize: Callable[[str], Awaitable[str]],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """The history the turn reads, and the summary to keep on the thread when a new one was made (None otherwise). The
    summary is built from the messages' text only, never their reads, skills or plans."""
    if len(history) <= COMPACT_AFTER:
        return history, None
    upto = (len(history) - COMPACT_STEP) // COMPACT_STEP * COMPACT_STEP
    made: dict[str, Any] | None = None
    if held is not None and held.get("upto") == upto and held.get("text"):
        text = str(held["text"])
    else:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in history[:upto] if m.get("content"))
        text = (await summarize(transcript)).strip()
        made = {"upto": upto, "text": text}
    return [{"role": "assistant", "content": f"{SUMMARY_LEAD} {text}"}, *history[upto:]], made
