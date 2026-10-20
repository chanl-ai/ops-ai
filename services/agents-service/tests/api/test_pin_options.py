"""The agent page's guardrail, widget and skill pickers (c-136), one test per failure row in the card's tasks file:
F1 an item past the first page not findable; F2 a deprecated, retired or unpublished item offered for a new pin; F3 a
widget needing an ungranted tool offered as choosable; F4 another team's widget offered; F5 a held skill offered
again; F6 wildcards matching every row."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.engine.test_lifecycle_rights import BUILDER, person, stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

from .test_agent_registry import _app, _ok  # pyright: ignore[reportPrivateUsage]
from .test_skills import HARDSHIP, _published  # pyright: ignore[reportPrivateUsage]
from .test_widget_registry import LIMIT_CARD

RULE = {"name": "Rule", "topics": ["advice"], "message": "Not here."}


async def _guardrail(c: AsyncClient, name: str) -> dict[str, Any]:
    g = _ok(await c.post("/v1/guardrails", json={**RULE, "name": name}), 201)
    return _ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}), 201)


async def _widget(c: AsyncClient, name: str, **extra: Any) -> dict[str, Any]:
    w = _ok(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": name, **extra}), 201)
    return _ok(await c.post(f"/v1/widgets/{w['widgetId']}/publish-requests", json={}), 201)


def _labels(page: dict[str, Any]) -> list[str]:
    return [o["label"] for o in page["data"]]


async def test_f1_an_item_past_the_first_page_is_found(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        for i in range(30):
            await _guardrail(c, f"Rule {i:02d}")
        found = _ok(await c.get("/v1/guardrails/options", params={"search": "rule 29", "limit": 5}))
        assert _labels(found) == ["Rule 29"]
        first = _ok(await c.get("/v1/guardrails/options", params={"search": "rule", "limit": 25}))
        assert len(first["data"]) == 25 and first["nextCursor"] == "25"


async def test_f2_deprecated_retired_and_unpublished_items_are_not_offered(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        old = await _guardrail(c, "Old rule")
        _ok(await c.post(f"/v1/guardrails/{old['id']}/status", json={"status": "deprecated"}))
        _ok(await c.post("/v1/guardrails", json={**RULE, "name": "Draft rule"}), 201)
        assert _labels(_ok(await c.get("/v1/guardrails/options", params={"search": "rule"}))) == []
        held = _ok(await c.get("/v1/guardrails/options", params={"ids": [old["id"]]}))
        assert _labels(held) == ["Old rule"], "a pin already held keeps its label"
        gone = await _widget(c, "Gone card")
        _ok(await c.post(f"/v1/widgets/{gone['widgetId']}/retire", json={"reason": "Replaced"}))
        _ok(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": "Draft card"}), 201)
        assert _labels(_ok(await c.get("/v1/widgets/options", params={"search": "card"}))) == []
        _ok(await c.post("/v1/skills", json={**HARDSHIP, "name": "Draft skill"}), 201)
        skills = _ok(await c.get("/v1/agents/ag_branch/skills/options", params={"search": "draft"}))
        assert _labels(skills) == []


async def test_f3_a_widget_needing_an_ungranted_tool_is_disabled_with_the_reason(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        await _widget(c, "Limit card")
        without = _ok(await c.get("/v1/widgets/options", params={"search": "limit card"}))["data"][0]
        assert without["disabled"] and "lookup_account" in without["disabled"]
        granted = _ok(
            await c.get("/v1/widgets/options", params={"search": "limit card", "granted": ["lookup_account"]})
        )
        assert granted["data"][0]["disabled"] is None


async def test_f4_another_teams_widget_is_not_offered(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, _ = stack
    lending = person("lena", "team_lending", "builder")
    made = await c.post("/v1/widgets", json={**LIMIT_CARD, "name": "Ops card"}, headers=BUILDER)
    assert made.status_code == 201, made.text
    await c.post(f"/v1/widgets/{made.json()['data']['widgetId']}/publish-requests", json={}, headers=BUILDER)
    mine = (await c.get("/v1/widgets/options", params={"search": "ops card"}, headers=BUILDER)).json()["data"]
    assert _labels(mine) == ["Ops card"]
    theirs = await c.get("/v1/widgets/options", params={"search": "ops card"}, headers=lending)
    assert theirs.status_code == 200, theirs.text
    assert _labels(theirs.json()["data"]) == [], "a builder of another team is not offered it"


async def test_f5_a_skill_the_agent_holds_is_not_offered_again(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        s = await _published(c)
        offered = _ok(await c.get("/v1/agents/ag_branch/skills/options", params={"search": "hardship"}))
        assert [o["id"] for o in offered["data"]] == [s["id"]] and offered["data"][0]["disabled"] is None
        attached = await c.put(f"/v1/agents/ag_branch/skills/{s['id']}", json={})
        assert attached.status_code == 200, attached.text
        again = _ok(await c.get("/v1/agents/ag_branch/skills/options", params={"search": "hardship"}))
        assert again["data"] == []


async def test_f6_wildcards_match_only_themselves(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        for n in ("Rate 100%", "Rate 1000"):
            await _guardrail(c, n)
            await _widget(c, n)
        assert _labels(_ok(await c.get("/v1/guardrails/options", params={"search": "100%"}))) == ["Rate 100%"]
        assert _labels(_ok(await c.get("/v1/widgets/options", params={"search": "100%"}))) == ["Rate 100%"]


async def test_a_new_pin_without_a_version_takes_the_published_one(tmp_path: Path) -> None:
    async with _app(str(tmp_path / "db.sqlite")) as c:
        g = await _guardrail(c, "Picked rule")
        saved = await c.patch("/v1/agents/ag_branch", json={"guardrailPins": [{"guardrailId": g["id"]}]})
        assert saved.status_code == 200, saved.text
        assert [(p["guardrailId"], p["version"]) for p in saved.json()["data"]["guardrailPins"]] == [(g["id"], 1)]


async def test_f7_a_loading_filter_keeps_pages_full(tmp_path: Path) -> None:
    """F7 (tick 18): filtering loading after the page was read returned short pages and stopped the cursor early."""
    async with _app(str(tmp_path / "db.sqlite")) as c:
        for i in range(4):
            await _published(c, {**HARDSHIP, "name": f"A match {i}"})
            await _published(c, {**HARDSHIP, "name": f"Z always {i}", "loading": "always", "useWhen": ""})
        page = _ok(await c.get("/v1/agents/ag_branch/skills/options", params={"loading": "always", "limit": 3}))
        assert len(page["data"]) == 3 and page["nextCursor"] == "3", page
        assert all(o["label"].startswith("Z always") for o in page["data"]), (
            "on-match skills sort first, so a late filter comes up short"
        )
