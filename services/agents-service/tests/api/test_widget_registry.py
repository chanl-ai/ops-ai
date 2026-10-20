"""Authoring widget templates through /v1/widgets (c-082), by failure mode: a tree that binds a field its schema lacks
or uses something outside the catalogue saved; a seeded platform widget edited; a draft pinned before it is published;
a published version changed in place; a retired widget pinned again; another team's widget listed; a member of the
owning team outside the builder and admin roles creating, saving, publishing or retiring one."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.deps import Runtime
from ops_agents.api.widgets import listed, widgets
from ops_agents.store.widgets import WidgetRegistry
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER, stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture

from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]

FRAUD = "ag_fraud"
LIMIT_CARD: dict[str, Any] = {
    "name": "Wire limit card",
    "useWhen": "The person asks for an account's wire limits.",
    "tree": {
        "type": "card",
        "title": {"$bind": "/account"},
        "children": [
            {"type": "metric", "label": "Daily", "value": {"$bind": "/daily"}, "unit": "USD"},
            {
                "type": "button",
                "label": "Look it up",
                "requires": "lookup_account",
                "reply": {"text": "Look up this account.", "values": {"query": {"$bind": "/account"}}},
            },
        ],
    },
    "dataSchema": {
        "type": "object",
        "required": ["account", "daily"],
        "properties": {"account": {"type": "string"}, "daily": {"type": "number"}},
    },
    "sample": {"account": "CHQ-2219", "daily": 25000},
}


async def test_a_builder_creates_saves_publishes_and_pins_a_widget(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        made = _data(await c.post("/v1/widgets", json=LIMIT_CARD), 201)
        assert (made["widgetId"], made["version"], made["status"]) == ("wire-limit-card", 1, "draft")
        assert made["requiresTools"] == ["lookup_account"]
        early = await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "wire-limit-card"}]})
        assert early.status_code == 422, "a draft cannot be pinned"

        edited = _data(
            await c.patch("/v1/widgets/wire-limit-card", json={**LIMIT_CARD, "useWhen": "Wire limits for one account."})
        )
        assert (edited["version"], edited["status"]) == (1, "draft"), "a draft is edited in place"
        published = _data(await c.post("/v1/widgets/wire-limit-card/publish-requests", json={"note": "first"}), 201)
        assert published["status"] == "published"
        again = _data(await c.patch("/v1/widgets/wire-limit-card", json={**LIMIT_CARD, "name": "Wire limits"}))
        assert (again["version"], again["status"]) == (2, "draft"), "a published version is never changed in place"

        pinned = _data(
            await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "wire-limit-card", "version": 1}]})
        )
        assert pinned["widgetPins"][0]["name"] == "Wire limit card", "the pin keeps the version it named"
        listed_ = {w["widgetId"]: w for w in _data(await c.get("/v1/widgets"))}
        assert listed_["wire-limit-card"]["version"] == 2 and "hold-review" in listed_, "seeded and authored, together"


async def test_a_tree_outside_the_catalogue_or_its_schema_is_refused(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        unbound = {**LIMIT_CARD, "tree": {"type": "text", "text": {"$bind": "/secret"}}}
        r = await c.post("/v1/widgets", json=unbound)
        assert r.status_code == 422 and "/secret" in r.text, r.text
        html = {**LIMIT_CARD, "tree": {"type": "html", "text": "<b>x</b>"}}
        r = await c.post("/v1/widgets", json=html)
        assert r.status_code == 422 and "not in the catalogue" in r.text, r.text
        seeded = await c.patch("/v1/widgets/hold-review", json=LIMIT_CARD)
        assert seeded.status_code == 409, "a platform widget is not edited here"


async def test_a_retired_widget_takes_no_new_pins(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        _data(await c.post("/v1/widgets", json=LIMIT_CARD), 201)
        _data(await c.post("/v1/widgets/wire-limit-card/publish-requests", json={}), 201)
        retired = _data(await c.post("/v1/widgets/wire-limit-card/retire", json={"reason": "Replaced"}))
        assert retired["status"] == "deprecated"
        r = await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "wire-limit-card"}]})
        assert r.status_code == 422 and "wire-limit-card" in r.text, r.text


async def test_another_teams_widget_is_not_listed(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        _data(await c.post("/v1/widgets", json=LIMIT_CARD), 201)
        rt: Runtime = app.state.runtime
        mine = [w["widgetId"] for w in await listed(rt, None)]
        theirs = [w["widgetId"] for w in await listed(rt, ["team_lending"])]
        assert "wire-limit-card" in mine and "wire-limit-card" not in theirs
        assert "hold-review" in theirs, "the seeded library is platform-wide"


async def test_only_builders_and_admins_of_the_owning_team_change_a_widget(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    assert (await c.post("/v1/widgets", json=LIMIT_CARD, headers=VIEWER)).status_code == 403
    made = await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER)
    assert made.status_code == 201, made.text
    url = "/v1/widgets/wire-limit-card"
    assert (await c.patch(url, json=LIMIT_CARD, headers=VIEWER)).status_code == 403
    assert (await c.post(f"{url}/publish-requests", json={}, headers=VIEWER)).status_code == 403
    assert (await c.post(f"{url}/retire", json={"reason": "x"}, headers=VIEWER)).status_code == 403
    saved = await c.patch(url, json={**LIMIT_CARD, "useWhen": "Wire limits."}, headers=BUILDER)
    assert saved.status_code == 200, saved.text


async def test_the_paged_list_answers_one_page_and_the_searched_total(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _app(tmp_path) as (c, _):
        for i in range(3):
            _data(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": f"Limit card {i}"}), 201)
        whole = cast(list[dict[str, Any]], _data(await c.get("/v1/widgets")))
        assert isinstance(whole, list), "without page the agent page's picker still reads the whole list"

        # A page reads only its own rows: the whole-table read is never called.
        async def no_whole_table(_self: WidgetRegistry) -> list[dict[str, Any]]:
            raise AssertionError("a page must not load every widget")

        monkeypatch.setattr(WidgetRegistry, "rows", no_whole_table)
        p2 = _data(await c.get("/v1/widgets", params={"page": 2, "pageSize": 2}))
        assert p2["pagination"]["total"] == len(whole) and len(p2["data"]) == 2
        assert [w["widgetId"] for w in p2["data"]] == [w["widgetId"] for w in whole[2:4]], "the same order, paged"
        hit = _data(await c.get("/v1/widgets", params={"page": 1, "search": "limit card 1"}))
        assert [w["widgetId"] for w in hit["data"]] == ["limit-card-1"] and hit["pagination"]["total"] == 1


async def test_the_store_answers_at_most_one_page(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        for i in range(5):
            _data(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": f"Limit card {i}"}), 201)
        reg = widgets(app.state.runtime)
        rows = await reg.page(None, "limit card", offset=1, limit=2)
        assert [r["name"] for r in rows] == ["Limit card 1", "Limit card 2"]
        assert await reg.count(None, "limit card") == 5 and await reg.count(["team_lending"], "limit card") == 0


async def test_wildcards_in_the_search_match_only_themselves(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        for n in ("Rate 100%", "Rate 1000", "a_b", "axb"):
            _data(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": n}), 201)
        for term, want in (("100%", ["Rate 100%"]), ("a_b", ["a_b"])):
            got = _data(await c.get("/v1/widgets", params={"page": 1, "search": term}))
            assert [w["name"] for w in got["data"]] == want, term
