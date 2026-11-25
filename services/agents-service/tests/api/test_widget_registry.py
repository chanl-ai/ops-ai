"""Authoring widget templates through /v1/widgets, by failure mode: a tree that binds a field its schema lacks
or uses something outside the catalogue saved; a seeded platform widget edited; a draft pinned before it is published;
a published version changed in place; a retired widget pinned again; a search wildcard matching more than itself.
Each route's replies and refusals by caller are pinned in test_widgets_route_pins.py."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..saves import save_agent
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
        early = await save_agent(c, FRAUD, {"widgetPins": [{"widgetId": "wire-limit-card"}]})
        assert early.status_code == 422, "a draft cannot be pinned"

        edited = _data(
            await c.patch("/v1/widgets/wire-limit-card", json={**LIMIT_CARD, "useWhen": "Wire limits for one account."})
        )
        assert (edited["version"], edited["status"]) == (1, "draft"), "a draft is edited in place"
        published = _data(await c.post("/v1/widgets/wire-limit-card/publish-requests", json={"note": "first"}), 201)
        assert published["status"] == "published"
        again = _data(await c.patch("/v1/widgets/wire-limit-card", json={**LIMIT_CARD, "name": "Wire limits"}))
        assert (again["version"], again["status"]) == (2, "draft"), "a published version is never changed in place"

        pinned = _data(await save_agent(c, FRAUD, {"widgetPins": [{"widgetId": "wire-limit-card", "version": 1}]}))
        assert pinned["widgetPins"][0]["name"] == "Wire limit card", "the pin keeps the version it named"
        listed_ = {w["widgetId"]: w for w in _data(await c.get("/v1/widgets"))["data"]}
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
        r = await save_agent(c, FRAUD, {"widgetPins": [{"widgetId": "wire-limit-card"}]})
        assert r.status_code == 422 and "wire-limit-card" in r.text, r.text


async def test_wildcards_in_the_search_match_only_themselves(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        for n in ("Rate 100%", "Rate 1000", "a_b", "axb"):
            _data(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": n}), 201)
        for term, want in (("100%", ["Rate 100%"]), ("a_b", ["a_b"])):
            got = _data(await c.get("/v1/widgets", params={"page": 1, "search": term}))
            assert [w["name"] for w in got["data"]] == want, term
