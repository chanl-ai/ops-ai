"""Every /v1/widgets route's reply, status and error object, value by value, by failure mode: a template, page or
picker reply changing a key or a value the Widgets page or the agent page reads; a refusal (another team's widget, a
viewer, a seeded widget, a retired one, a publish already made) changing its status or code, so a change that was
refused is let through or a page cannot say why. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from ops_agents.api import publish_policy
from ops_agents.store.tenancy import tenant_scope
from ops_agents.store.widget_picker import WidgetPicker
from ops_store.team_scope import acting_as
from tests.api import test_write_approval_policy as platform_stub
from tests.api.test_reply_pins import FIXTURES, compare
from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_registry import LIMIT_CARD
from tests.api.test_widget_route_pins import _ENGINES, answer, client  # pyright: ignore[reportPrivateUsage]

__all__ = ["client"]


async def test_every_widgets_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c, seen = client, dict[str, Any]()
    seen["create"] = answer(await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER))
    second = {**LIMIT_CARD, "name": "Limit card two"}
    await c.post("/v1/widgets", json=second, headers=BUILDER)
    seen["create.viewer"] = answer(await c.post("/v1/widgets", json={**LIMIT_CARD, "name": "x"}, headers=VIEWER))
    seen["create.seededName"] = answer(
        await c.post("/v1/widgets", json={**LIMIT_CARD, "name": "Hold review"}, headers=BUILDER)
    )
    seen["create.outsideCatalogue"] = answer(
        await c.post("/v1/widgets", json={**LIMIT_CARD, "name": "y", "tree": {"type": "html"}}, headers=BUILDER)
    )

    url = "/v1/widgets/wire-limit-card"
    seen["read"] = answer(await c.get(url, headers=BUILDER))
    seen["read.seeded"] = answer(await c.get("/v1/widgets/hold-review", headers=BUILDER))
    seen["read.missing"] = answer(await c.get("/v1/widgets/wd_missing", headers=BUILDER))
    seen["read.otherTeam"] = answer(await c.get(url, headers=OUTSIDER))

    seen["save"] = answer(await c.patch(url, json={**LIMIT_CARD, "useWhen": "Wire limits."}, headers=BUILDER))
    seen["save.unknownField"] = answer(await c.patch(url, json={**LIMIT_CARD, "x": 1}, headers=BUILDER))
    seen["save.viewer"] = answer(await c.patch(url, json=LIMIT_CARD, headers=VIEWER))
    seen["save.otherTeam"] = answer(await c.patch(url, json=LIMIT_CARD, headers=OUTSIDER))
    seen["save.seeded"] = answer(await c.patch("/v1/widgets/hold-review", json=LIMIT_CARD, headers=BUILDER))

    seen["publish"] = answer(await c.post(f"{url}/publish-requests", json={"note": "first"}, headers=BUILDER))
    seen["publish.again"] = answer(await c.post(f"{url}/publish-requests", json={}, headers=BUILDER))
    seen["publish.viewer"] = answer(await c.post(f"{url}/publish-requests", json={}, headers=VIEWER))

    seen["list"] = answer(await c.get("/v1/widgets", headers=BUILDER))
    seen["list.page"] = answer(await c.get("/v1/widgets", params={"page": 2, "pageSize": 2}, headers=BUILDER))
    seen["list.pastTheEnd"] = answer(await c.get("/v1/widgets", params={"page": 9, "pageSize": 2}, headers=BUILDER))
    seen["list.search"] = answer(await c.get("/v1/widgets", params={"page": 1, "search": "limit"}, headers=BUILDER))
    seen["list.otherTeam"] = answer(await c.get("/v1/widgets", params={"page": 1}, headers=OUTSIDER))

    options = "/v1/widgets/options"
    seen["options"] = answer(await c.get(options, headers=BUILDER))
    seen["options.granted"] = answer(
        await c.get(options, params={"granted": ["lookup_account"], "limit": 2}, headers=BUILDER)
    )
    seen["options.next"] = answer(await c.get(options, params={"cursor": "2", "limit": 2}, headers=BUILDER))
    seen["options.search"] = answer(await c.get(options, params={"search": "wire"}, headers=BUILDER))
    seen["options.ids"] = answer(
        await c.get(options, params={"ids": ["limit-card-two", "hold-review"]}, headers=BUILDER)
    )
    seen["options.otherTeam"] = answer(await c.get(options, params={"search": "wire"}, headers=OUTSIDER))

    seen["retire.noReason"] = answer(await c.post(f"{url}/retire", json={"reason": " "}, headers=BUILDER))
    seen["retire.viewer"] = answer(await c.post(f"{url}/retire", json={"reason": "Replaced"}, headers=VIEWER))
    seen["retire"] = answer(await c.post(f"{url}/retire", json={"reason": "Replaced"}, headers=BUILDER))
    seen["save.retired"] = answer(await c.patch(url, json=LIMIT_CARD, headers=BUILDER))
    seen["publish.retired"] = answer(await c.post(f"{url}/publish-requests", json={}, headers=BUILDER))
    compare(seen, FIXTURES / "reply-pins-widgets.json")


def _transactions() -> list[int]:
    """[transactions begun, transactions open now] on the test app's engine, kept as requests run."""
    held = [0, 0]

    def began(_conn: object) -> None:
        held[0] += 1
        held[1] += 1

    def ended(_conn: object) -> None:
        held[1] -= 1

    engine = _ENGINES[-1].sync_engine
    event.listen(engine, "begin", began)
    event.listen(engine, "commit", ended)
    event.listen(engine, "rollback", ended)
    return held


async def test_each_widgets_route_on_the_database_alone_holds_one_transaction(client: AsyncClient) -> None:
    """A route opening one transaction per store call: a save whose refusal checks and write land apart, or a page
    whose count and rows are read at different moments."""
    c, url = client, "/v1/widgets/wire-limit-card"
    await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER)
    steps: list[tuple[str, str, str, object]] = [
        ("create", "POST", "/v1/widgets", {**LIMIT_CARD, "name": "Limit card two"}),
        ("list", "GET", "/v1/widgets?page=1&pageSize=2", None),
        ("options", "GET", "/v1/widgets/options", None),
        ("save", "PATCH", url, {**LIMIT_CARD, "useWhen": "Wire limits."}),
        ("retire", "POST", f"{url}/retire", {"reason": "Replaced"}),
    ]
    held = _transactions()
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        held[0] = 0
        r = await c.request(method, path, json=body, headers=BUILDER)
        assert r.status_code in (200, 201), (name, r.text)
        counts[name] = held[0]
    assert counts == {name: 1 for name, *_ in steps}, counts


async def test_no_transaction_is_open_while_platform_service_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reading a widget asks platform-service for its team's name and a publish request asks for the publish-review
    policy: a request transaction held across either holds a connection for as long as platform-service takes."""
    c, url = client, "/v1/widgets/wire-limit-card"
    await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER)
    held, open_during = _transactions(), list[tuple[str, int]]()
    named, policy = platform_stub._Names.name, publish_policy.team_document  # pyright: ignore[reportPrivateUsage]

    async def name(self: Any, team_id: str) -> str | None:
        open_during.append(("name", held[1]))
        return await named(self, team_id)

    async def document(rt: Any) -> dict[str, Any] | None:
        open_during.append(("policy", held[1]))
        return await policy(rt)

    monkeypatch.setattr(platform_stub._Names, "name", name)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(publish_policy, "team_document", document)
    read = await c.get(url, headers=BUILDER)
    asked = await c.post(f"{url}/publish-requests", json={}, headers=BUILDER)
    assert (read.status_code, asked.status_code, open_during) == (200, 201, [("name", 0), ("policy", 0)]), asked.text


async def test_the_picker_query_holds_the_acting_team_when_every_team_is_let_through(client: AsyncClient) -> None:
    """The picker read naming several teams while one acts: with the database policy letting every team through, the
    query alone keeps another team's published widget out."""
    c = client
    for headers, name in ((BUILDER, "Ops limit card"), (OUTSIDER, "Fraud limit card")):
        made = (await c.post("/v1/widgets", json={**LIMIT_CARD, "name": name}, headers=headers)).json()["data"]
        await c.post(f"/v1/widgets/{made['widgetId']}/publish-requests", json={}, headers=headers)
    with tenant_scope("local"), acting_as("team_ops"):
        rows = await WidgetPicker(_ENGINES[-1]).pinnable(["team_ops", "team_fraud"], "limit card", 0, 10)
    assert [(r.id, r.shown) for r in rows] == [("ops-limit-card", 1)]
