"""The thread event log's shapes: every run event in the designed shape `{id, seq, type, threadId, runId, node, at,
data}`. The table and its queries are `store/events.py`.

`seq` rises by one per thread across runs. The run stream still sends the earlier `{event, runId, seq}` frames for
one release (docs/architecture/api.md); this log and the routes that read it use the designed shape.
"""

from __future__ import annotations

from typing import Any, cast

REVIEW_KINDS = ("review", "approval")
_RENAMED = {
    "run_start": "started",
    "node_start": "node",
    "node_end": "node",
    "error": "failed",
    "tool_start": "tool_call",
    "tool_end": "tool_call",
}


def _field(d: Any, key: str) -> Any:
    return cast(dict[str, Any], d).get(key) if isinstance(d, dict) else None


def designed_type(legacy: dict[str, Any]) -> str | None:
    """The designed type for a run-stream event, or None when it adds nothing (an interrupted `end` follows its
    `waiting`)."""
    name = str(legacy["event"])
    data = legacy.get("data")
    if name == "interrupt":
        return "waiting_review" if _field(_field(data, "payload"), "kind") in REVIEW_KINDS else "waiting"
    if name == "end":
        return "finished" if _field(data, "status") == "done" else None
    return _RENAMED.get(name, name)[:32]
