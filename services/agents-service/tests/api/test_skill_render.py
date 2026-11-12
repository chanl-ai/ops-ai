"""POST /v1/skills/{id}/render and parts of one skill. Failure modes: a draft or deprecated skill's text served; the
newest draft served in place of the published version; a required input missing and the text left with {{name}};
a part naming a tool the skill does not hold, or two parts with one slug, saved; a picked part rendered without
the shared overview or with another part's inputs; the published list describing the draft."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_skills import HARDSHIP, _published  # pyright: ignore[reportPrivateUsage]

BRIEF: dict[str, Any] = {
    **HARDSHIP,
    "name": "Client brief",
    "instructions": "Prepare a brief for {{client}}. {{note}}",
    "inputs": [{"name": "client", "required": True}, {"name": "note"}],
}
SALES: dict[str, Any] = {
    **HARDSHIP,
    "name": "Sales",
    "instructions": "Work in the bank's CRM.",
    "parts": [
        {
            "slug": "prepare-meeting",
            "name": "Prepare a client meeting",
            "useWhen": "Before a client meeting.",
            "instructions": "Brief me on {{client}}.",
            "inputs": [{"name": "client", "required": True}],
        },
        {
            "slug": "update-opportunity",
            "name": "Update an opportunity",
            "useWhen": "After a deal moves.",
            "instructions": "Change the opportunity.",
            "toolIds": ["lookup_customer"],
        },
    ],
}


async def test_only_the_published_version_renders(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        draft = _ok(await c.post("/v1/skills", json={**BRIEF, "name": "Draft only"}), 201)
        r = await c.post(f"/v1/skills/{draft['id']}/render", json={"inputs": {"client": "Okafor"}})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "skill_not_published")

        s = await _published(c, BRIEF)
        _ok(await c.put(f"/v1/skills/{s['id']}/draft", json={"instructions": "DRAFT {{client}}", "baseVersion": 1}))
        got = _ok(await c.post(f"/v1/skills/{s['id']}/render", json={"inputs": {"client": "Okafor"}}))
        assert got["version"] == 1 and got["text"].startswith("Prepare a brief for Okafor."), got

        _ok(await c.post(f"/v1/skills/{s['id']}/deprecate", json={"reason": "replaced"}))
        r = await c.post(f"/v1/skills/{s['id']}/render", json={"inputs": {"client": "Okafor"}})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "skill_not_published")


async def test_a_required_input_is_checked_and_an_empty_optional_one_leaves_no_placeholder(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c, BRIEF)
        r = await c.post(f"/v1/skills/{s['id']}/render", json={"inputs": {"note": "x"}})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "missing_input")
        assert "client" in r.json()["error"]["message"]
        got = _ok(await c.post(f"/v1/skills/{s['id']}/render", json={"inputs": {"client": "Okafor"}}))
        assert "{{" not in got["text"] and "Okafor" in got["text"], got


async def test_parts_are_checked_listed_and_render_with_the_overview(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        bad_tool = [{**SALES["parts"][1], "toolIds": ["request_document"]}]
        r = await c.post("/v1/skills", json={**SALES, "parts": bad_tool})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "part_tool_not_in_skill")
        twice = [SALES["parts"][0], {**SALES["parts"][1], "slug": "prepare-meeting"}]
        r = await c.post("/v1/skills", json={**SALES, "parts": twice})
        assert (r.status_code, r.json()["error"]["code"]) == (400, "duplicate_part")

        s = await _published(c, SALES)
        rows = _ok(await c.get("/v1/skills", params={"view": "published"}))["data"]
        row = next(x for x in rows if x["id"] == s["id"])
        assert [p["slug"] for p in row["parts"]] == ["prepare-meeting", "update-opportunity"]
        assert row["parts"][0]["inputs"][0]["name"] == "client"

        r = await c.post(f"/v1/skills/{s['id']}/render", json={"part": "update-opportunity", "inputs": {"client": "x"}})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "unknown_input")
        got = _ok(
            await c.post(
                f"/v1/skills/{s['id']}/render", json={"part": "prepare-meeting", "inputs": {"client": "Okafor"}}
            )
        )
        assert got["part"] == "prepare-meeting"
        assert got["text"].startswith("Work in the bank's CRM.") and "Brief me on Okafor." in got["text"], got

        plain = await _published(c, {**HARDSHIP, "name": "No parts"})
        assert "parts" not in plain["content"]
