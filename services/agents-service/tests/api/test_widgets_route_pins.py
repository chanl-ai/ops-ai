"""Every /v1/widgets route's reply, status and error object, value by value, by failure mode: a template, page or
picker reply changing a key or a value the Widgets page or the agent page reads; a refusal (another team's widget, a
viewer, a seeded widget, a retired one, a publish already made) changing its status or code, so a change that was
refused is let through or a page cannot say why. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_reply_pins import FIXTURES, compare
from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_registry import LIMIT_CARD
from tests.api.test_widget_route_pins import answer, client  # a fixture

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
