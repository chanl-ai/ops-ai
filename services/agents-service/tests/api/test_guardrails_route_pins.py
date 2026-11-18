"""Every /v1/guardrails route's reply, status and error object, value by value, by failure mode: a guardrail, page or
picker reply changing a key or a value the Guardrails page or the agent page reads; a refusal (a viewer, another team,
a version that is not the newest draft, a delete by someone else) changing its status or code, so a change that was
refused is let through or a page cannot say why. Regenerate with `AGENTS_REPIN=1` only for an intended change."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient

from ops_agents.api import publish_policy
from ops_agents.store.guardrails import GuardrailRegistry
from ops_agents.store.tenancy import OWNER
from ops_store import isolation
from ops_store.team_scope import acting_as
from tests.api.test_reply_pins import FIXTURES, compare
from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_route_pins import _ENGINES, answer, client  # pyright: ignore[reportPrivateUsage]
from tests.api.test_widgets_route_pins import _transactions  # pyright: ignore[reportPrivateUsage]

__all__ = ["client"]

RULE = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't give investment advice."}


async def test_every_guardrails_route_keeps_its_reply_status_and_error_object(client: AsyncClient) -> None:
    c, seen = client, dict[str, Any]()
    made = await c.post("/v1/guardrails", json=RULE, headers=BUILDER)
    seen["create"] = answer(made)
    gid = made.json()["data"]["id"]
    for i in range(3):
        await c.post("/v1/guardrails", json={**RULE, "name": f"Same rule {i}"}, headers=BUILDER)
    await c.post("/v1/guardrails", json={**RULE, "name": "Fraud rule"}, headers=OUTSIDER)
    seen["create.viewer"] = answer(await c.post("/v1/guardrails", json={**RULE, "name": "x"}, headers=VIEWER))
    seen["create.noTopic"] = answer(await c.post("/v1/guardrails", json={**RULE, "topics": [" "]}, headers=BUILDER))
    seen["create.unknownField"] = answer(await c.post("/v1/guardrails", json={**RULE, "x": 1}, headers=BUILDER))
    seen["create.noMessage"] = answer(await c.post("/v1/guardrails", json={**RULE, "message": ""}, headers=BUILDER))

    url = f"/v1/guardrails/{gid}"
    seen["read"] = answer(await c.get(url, headers=BUILDER))
    seen["read.missing"] = answer(await c.get("/v1/guardrails/gr_missing", headers=BUILDER))
    seen["read.otherTeam"] = answer(await c.get(url, headers=OUTSIDER))

    seen["edit"] = answer(await c.patch(url, json={"topics": ["tax advice"]}, headers=BUILDER))
    seen["edit.viewer"] = answer(await c.patch(url, json={"topics": ["x"]}, headers=VIEWER))
    seen["edit.otherTeam"] = answer(await c.patch(url, json={"topics": ["x"]}, headers=OUTSIDER))

    seen["publish.notNewest"] = answer(await c.post(f"{url}/publish-requests", json={"version": 2}, headers=BUILDER))
    seen["publish"] = answer(await c.post(f"{url}/publish-requests", json={"version": 1}, headers=BUILDER))
    seen["publish.again"] = answer(await c.post(f"{url}/publish-requests", json={"version": 1}, headers=BUILDER))
    seen["publish.viewer"] = answer(await c.post(f"{url}/publish-requests", json={"version": 1}, headers=VIEWER))
    decide = f"{url}/publish-requests/GRP-missing/decision"
    seen["decide.missing"] = answer(await c.post(decide, json={"decision": "approved"}, headers=BUILDER))
    seen["decide.unknown"] = answer(await c.post(decide, json={"decision": "maybe"}, headers=BUILDER))

    seen["list"] = answer(await c.get("/v1/guardrails", headers=BUILDER))
    seen["list.page"] = answer(await c.get("/v1/guardrails", params={"page": 2, "pageSize": 2}, headers=BUILDER))
    seen["list.pastTheEnd"] = answer(await c.get("/v1/guardrails", params={"page": 9, "pageSize": 2}, headers=BUILDER))
    seen["list.search"] = answer(await c.get("/v1/guardrails", params={"page": 1, "search": "rule 1"}, headers=BUILDER))
    seen["list.otherTeam"] = answer(await c.get("/v1/guardrails", params={"page": 1}, headers=OUTSIDER))

    options = "/v1/guardrails/options"
    seen["options"] = answer(await c.get(options, headers=BUILDER))
    seen["options.search"] = answer(await c.get(options, params={"search": "nothing"}, headers=BUILDER))
    seen["options.ids"] = answer(await c.get(options, params={"ids": [gid]}, headers=BUILDER))
    seen["options.otherTeam"] = answer(await c.get(options, headers=OUTSIDER))

    seen["status.viewer"] = answer(await c.post(f"{url}/status", json={"status": "deprecated"}, headers=VIEWER))
    seen["status"] = answer(await c.post(f"{url}/status", json={"status": "deprecated"}, headers=BUILDER))
    seen["delete.viewer"] = answer(await c.delete(url, headers=VIEWER))
    seen["delete.otherTeam"] = answer(await c.delete(url, headers=OUTSIDER))
    seen["delete"] = answer(await c.delete(url, headers=BUILDER))
    seen["read.deleted"] = answer(await c.get(url, headers=BUILDER))
    # The new guardrail's id is random; the scrubber hides it in ids but not inside a message.
    compare(json.loads(json.dumps(seen).replace(gid, "<gr>")), FIXTURES / "reply-pins-guardrails.json")


async def test_each_guardrails_route_on_the_database_alone_holds_one_transaction(client: AsyncClient) -> None:
    """A route opening one transaction per store call: an edit whose permission check and save land apart, a delete
    whose pin check and removal land apart, or a page whose count and rows are read at different moments."""
    c = client
    gid = (await c.post("/v1/guardrails", json=RULE, headers=BUILDER)).json()["data"]["id"]
    url = f"/v1/guardrails/{gid}"
    steps: list[tuple[str, str, str, object]] = [
        ("create", "POST", "/v1/guardrails", {**RULE, "name": "Second"}),
        ("list", "GET", "/v1/guardrails?page=1&pageSize=2", None),
        ("options", "GET", "/v1/guardrails/options", None),
        ("read", "GET", url, None),
        ("edit", "PATCH", url, {"topics": ["tax advice"]}),
        ("status", "POST", f"{url}/status", {"status": "deprecated"}),
        ("delete", "DELETE", url, None),
    ]
    held = _transactions()
    counts: dict[str, int] = {}
    for name, method, path, body in steps:
        held[0] = 0
        r = await c.request(method, path, json=body, headers=BUILDER)
        assert r.status_code in (200, 201, 204), (name, r.text)
        counts[name] = held[0]
    assert counts == {name: 1 for name, *_ in steps}, counts


async def test_no_transaction_is_open_while_platform_service_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A publish request reads the team's publish-review policy from platform-service: a request transaction held
    across it holds a connection for as long as platform-service takes."""
    c = client
    gid = (await c.post("/v1/guardrails", json=RULE, headers=BUILDER)).json()["data"]["id"]
    held, open_during = _transactions(), list[int]()
    policy = publish_policy.team_document

    async def document(rt: Any) -> dict[str, Any] | None:
        open_during.append(held[1])
        return await policy(rt)

    monkeypatch.setattr(publish_policy, "team_document", document)
    asked = await c.post(f"/v1/guardrails/{gid}/publish-requests", json={"version": 1}, headers=BUILDER)
    assert (asked.status_code, open_during) == (201, [0]), asked.text


async def test_the_page_query_holds_the_acting_team_when_every_team_is_let_through(client: AsyncClient) -> None:
    """The page and its count with the database policy letting every team through: the query alone keeps another
    team's guardrail out."""
    c = client
    for headers, name in ((BUILDER, "Ops rule"), (OUTSIDER, "Fraud rule")):
        await c.post("/v1/guardrails", json={**RULE, "name": name}, headers=headers)
    reg = GuardrailRegistry(_ENGINES[-1])
    with isolation.tenant_wide(OWNER, tenant_id="local"), acting_as("team_ops"):
        names = [r["name"] for r in await reg.page("rule", 0, 10)]
        total = await reg.count("rule")
    assert (names, total) == (["Ops rule"], 1)
