"""Widgets an agent shows in chat (c-082), through the real routes, by failure mode: the library not served, a pin
to a template that does not exist saved, a draft's widgets reaching what is live before a publish, a pinned widget not
reaching the turn's present tool, and a template or composed part not reaching the chat stream or lost on reload."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from ops_agents.api.deps import Runtime
from tests.conftest import sse_events

from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]

FRAUD = "ag_fraud"
HOLD = {
    "holdId": "hold_204",
    "payee": "Acme Supplies Ltd",
    "amount": 12500,
    "currency": "USD",
    "status": "held",
    "reason": "First payment to a new payee",
    "account": "CHQ-2219",
}


async def _ask(c: Any, tid: str, args: dict[str, Any]) -> list[dict[str, Any]]:
    res = await c.post(
        f"/chat/threads/{tid}/messages",
        json={"content": f"call present {json.dumps(args)}"},
        headers={"Accept": "text/event-stream"},
    )
    assert res.status_code == 200, res.text
    return [e["part"] for e in sse_events(res.text) if e.get("type") == "part"]


async def test_the_library_lists_each_published_widget_with_its_schema_and_sample(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        listed = _data(await c.get("/v1/widgets"))
        assert [w["widgetId"] for w in listed] == ["account-snapshot", "case-summary", "hold-review"]
        hold = next(w for w in listed if w["widgetId"] == "hold-review")
        assert hold["dataSchema"]["required"][0] == "holdId" and hold["sample"]["holdId"] == "hold_204"


async def test_a_pin_to_a_widget_that_does_not_exist_is_refused_naming_it(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        r = await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "fake-approval"}]})
        assert r.status_code == 422 and "fake-approval" in r.text, r.text


async def test_pinned_widgets_go_live_through_a_publish_and_draw_in_chat(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        rt: Runtime = app.state.runtime
        saved = _data(
            await c.patch(
                f"/v1/agents/{FRAUD}",
                json={"widgetPins": [{"widgetId": "hold-review"}], "widgets": {"compose": True, "perTurn": 2}},
            )
        )
        assert saved["widgetPins"] == [
            {"widgetId": "hold-review", "version": 1, "name": "Hold review", "requiresTools": ["lookup_account"]}
        ]
        assert saved["widgets"] == {"compose": True, "perTurn": 2}
        live = rt.catalog.agent(FRAUD)
        assert live is not None and live.widgets == [], "a draft's widgets are not what chat serves"
        changes = _data(await c.get(f"/v1/agents/{FRAUD}/versions"))[0]["changes"]
        assert "Changed widgets" in changes and "Changed widget settings" in changes

        _data(await c.post(f"/v1/agents/{FRAUD}/publish-requests", json={"version": saved["version"]}), 201)
        live = rt.catalog.agent(FRAUD)
        assert live is not None and [w.widget_id for w in live.widgets] == ["hold-review"] and live.compose

        tid = _data(await c.post("/chat/threads", json={"agentId": FRAUD, "kbIds": []}), 201)["id"]
        (filled,) = await _ask(c, tid, {"widget": "hold-review", "data": HOLD})
        assert filled["template"] == {"id": "hold-review", "version": 1, "name": "Hold review"}
        assert filled["layout"]["title"] == "Acme Supplies Ltd" and "shape" not in filled
        (composed,) = await _ask(c, tid, {"layout": {"type": "text", "text": "Two holds are open."}})
        assert composed["layout"] == {"type": "text", "text": "Two holds are open."} and "template" not in composed

        kept: list[dict[str, Any]] = _data(await c.get(f"/chat/threads/{tid}"))["messages"]
        parts = [p for m in kept for p in cast(list[dict[str, Any]], m.get("parts") or [])]
        layouts = [p["layout"] for p in parts]
        assert len(layouts) == 2, "both parts are kept, so a reload draws what was shown"


async def test_a_widget_whose_button_needs_a_tool_the_agent_lacks_cannot_be_pinned(tmp_path: Path) -> None:
    """Case summary's button asks for request_document, which Wire Fraud Sentinel does not hold: the pin is refused
    naming the tool. Taking away a tool a pinned widget's button needs is refused the same way."""
    async with _app(tmp_path) as (c, _):
        r = await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "case-summary"}]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "widget_needs_tool", r.text
        assert "request_document" in r.json()["error"]["message"]
        _data(await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "hold-review"}]}))
        dropped = await c.patch(f"/v1/agents/{FRAUD}", json={"toolIds": ["place_wire_hold"]})
        assert dropped.status_code == 422 and "lookup_account" in dropped.text, dropped.text


async def test_a_click_on_a_granted_action_calls_that_tool_once(tmp_path: Path) -> None:
    """The button's reply names its action; the agent's turn calls that granted tool once, through its normal path."""
    async with _app(tmp_path) as (c, _):
        saved = _data(await c.patch(f"/v1/agents/{FRAUD}", json={"widgetPins": [{"widgetId": "hold-review"}]}))
        _data(await c.post(f"/v1/agents/{FRAUD}/publish-requests", json={"version": saved["version"]}), 201)
        tid = _data(await c.post("/chat/threads", json={"agentId": FRAUD, "kbIds": []}), 201)["id"]
        res = await c.post(
            f"/chat/threads/{tid}/messages",
            json={"content": "Look up this account. (action: lookup_account, query: CHQ-2219)"},
            headers={"Accept": "text/event-stream"},
        )
        ends = [e["call"] for e in sse_events(res.text) if e.get("type") == "tool_end"]
        assert [(t["name"], t["status"]) for t in ends] == [("lookup_account", "success")], ends
        assert ends[0]["input"] == {"query": "CHQ-2219"}
