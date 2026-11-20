"""A skill written as text through /v1/skills, by failure mode: a mention of a tool that no longer exists refusing
the save, or not blocking the publish, or not pointing at its line; a write tool with no rule check refusing a text
save; the editor's read call reading a text differently from the save; a skill saved as steps showing no text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]

TEXT = """Look the customer up with @tool:lookup_customer
if they sound upset:
    Place a hold with @tool:place_wire_hold
else:
    Ask for the email they used with @tool:retired_lookup
"""
SKILL: dict[str, Any] = {
    "name": "Customer lookup",
    "useWhen": "The person asks about their account.",
    "instructions": "Be brief.",
    "ownerTeam": "Retail",
}


async def test_a_text_with_a_deleted_tool_saves_and_only_its_publish_is_blocked_at_the_line(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = _ok(await c.post("/v1/skills", json=SKILL), 201)
        assert s["text"] == "Be brief.", "a skill saved before the text editor shows its instructions as text"
        reading = _ok(await c.post(f"/v1/skills/{s['id']}/text", json={"text": TEXT}))
        d = _ok(await c.put(f"/v1/skills/{s['id']}/draft", json={"source": TEXT, "baseVersion": 1}))
        assert d["text"] == TEXT and d["content"]["instructions"] == TEXT.strip()
        steps = d["content"]["steps"]
        assert [x.get("use", {}).get("id") for x in steps] == ["lookup_customer", "place_wire_hold", "retired_lookup"]
        assert reading["steps"] == len(steps), "the read call and the save read the text the same way"
        assert [(e["line"], e["id"]) for e in reading["errors"]] == [(5, "tool:retired_lookup")]
        check = d["publishCheck"]
        assert not check["canRequest"]
        assert [(p["kind"], p["position"]["field"], p["position"]["index"]) for p in check["problems"]] == [
            ("missing_reference", "source", 5)
        ], "the write with no rule check is a hint, not a blocker"
        fixed = TEXT.replace("@tool:retired_lookup", "@tool:lookup_customer")
        d = _ok(await c.put(f"/v1/skills/{s['id']}/draft", json={"source": fixed, "baseVersion": 1}))
        assert d["publishCheck"]["canRequest"], d["publishCheck"]
