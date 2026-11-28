"""How many agents name each alias, served on the alias list, by failure mode: the count is joined per row from the
wrong alias or asked once per row instead of once per page; and an agents-service that does not answer fails the
list or reads as 0 agents, which looks safe to re-point. agents-service is a fake behind the real client."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from ops_identity import ServiceClient
from ops_identity.fastapi import current_principal, current_tenant_caller
from ops_models.alias_users import AgentsAliasUsers
from ops_models.app import create_models_app
from ops_service_kit.settings import Settings

from .conftest import Models
from .test_model_knobs import _alias  # pyright: ignore[reportPrivateUsage]
from .test_provider_keys import people
from .test_provider_registry import _client  # pyright: ignore[reportPrivateUsage]


def _app(models: Models, agents: httpx.MockTransport) -> object:
    http = httpx.AsyncClient(transport=agents, base_url="http://agents")
    client = ServiceClient.for_settings(Settings(), http, service="models", audience="agents", scopes=["agents:view"])
    app = create_models_app(models.engine, alias_users=AgentsAliasUsers(client))
    # The seeded account, which holds the seeded aliases.
    person = people("local")
    app.dependency_overrides[current_principal] = person
    app.dependency_overrides[current_tenant_caller] = person
    return app


async def test_the_alias_list_shows_each_alias_agent_count_from_one_call(models: Models) -> None:
    first, second = await _alias(models.client, "scripted", "m-1"), await _alias(models.client, "scripted", "m-2")
    asked: list[httpx.Request] = []

    def agents(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        names = parse_qs(request.url.query.decode())["aliases"][0].split(",")
        return httpx.Response(200, json={"success": True, "data": {n: 3 if n == first else 0 for n in names}})

    async with _client(_app(models, httpx.MockTransport(agents))) as c:
        listed = await c.get("/v1/models/aliases", params={"ids": [first, second]})

    assert listed.status_code == 200, listed.text
    used = {a["name"]: a["usedBy"] for a in listed.json()["data"]["data"]}
    assert used == {first: 3, second: 0}, used
    assert [r.url.path for r in asked] == ["/v1/model-alias-uses"], asked


async def test_an_agents_service_that_does_not_answer_leaves_the_count_unknown(models: Models) -> None:
    name = await _alias(models.client, "scripted", "m-1")

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async with _client(_app(models, httpx.MockTransport(down))) as c:
        listed = await c.get("/v1/models/aliases", params={"ids": name})

    assert listed.status_code == 200, listed.text
    assert [a["usedBy"] for a in listed.json()["data"]["data"]] == [None], listed.text
