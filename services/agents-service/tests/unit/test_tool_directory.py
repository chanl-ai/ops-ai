"""The agents side of c-048 G1, by failure mode: one tenant's tools served to another from the cache, a list nobody
vouched for served when tools-service is down, a stale list kept past its time, and a granted name the registry no
longer offers handed to the model anyway."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ops_agents.activities.tool_directory import ToolsOperations, ToolsUnavailable, grants_for
from ops_agents.store.tenancy import current_tenant, tenant_scope


def op(name: str, access: str = "read") -> dict[str, Any]:
    return {
        "name": name,
        "description": f"{name} does a thing",
        "access": access,
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        "requiresApproval": access != "read",
        "moduleId": "mod_bank",
        "moduleName": "Northfield Core Banking",
    }


class Tools:
    """tools-service's internal list, per tenant from the service token's tenant, counting requests."""

    def __init__(self, by_tenant: dict[str, list[dict[str, Any]]]) -> None:
        self.by_tenant = by_tenant
        self.requests: list[str] = []
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        tenant = request.headers["Authorization"].removeprefix("Bearer tok-")
        self.requests.append(tenant)
        if self.down:
            return httpx.Response(503)
        return httpx.Response(200, json={"success": True, "data": self.by_tenant.get(tenant, [])})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def directory(tools: Tools, clock: Clock) -> ToolsOperations:
    client = httpx.AsyncClient(transport=httpx.MockTransport(tools.handler), base_url="http://tools")
    return ToolsOperations(client, lambda: f"tok-{current_tenant()}", ttl_s=30, clock=clock)


async def test_each_tenant_gets_its_own_tools_even_from_the_cache() -> None:
    tools = Tools({"acme": [op("get_account")], "globex": [op("get_invoice")]})
    d = directory(tools, Clock())
    with tenant_scope("acme"):
        assert [o.name for o in await d.operations()] == ["get_account"]
    with tenant_scope("globex"):
        assert [o.name for o in await d.operations()] == ["get_invoice"]
    with tenant_scope("acme"):
        assert [o.name for o in await d.operations()] == ["get_account"]
    assert tools.requests == ["acme", "globex"]


async def test_the_list_is_asked_again_after_its_time() -> None:
    tools, clock = Tools({"acme": [op("get_account")]}), Clock()
    d = directory(tools, clock)
    with tenant_scope("acme"):
        await d.operations()
        clock.now = 29
        await d.operations()
        tools.by_tenant["acme"].append(op("update_address", "write"))
        clock.now = 31
        assert [o.name for o in await d.operations()] == ["get_account", "update_address"]
    assert tools.requests == ["acme", "acme"]


async def test_tools_service_down_is_refused_not_guessed() -> None:
    tools = Tools({"acme": [op("get_account")]})
    tools.down = True
    with tenant_scope("acme"), pytest.raises(ToolsUnavailable):
        await directory(tools, Clock()).operations()


async def test_a_run_gets_only_granted_names_the_registry_still_offers_with_their_schema() -> None:
    tools = Tools({"acme": [op("get_account"), op("update_address", "write")]})
    with tenant_scope("acme"):
        grants = await grants_for(
            directory(tools, Clock()), ["get_account", "hidden_since", "workflow:dispute_email", "update_address"]
        )
    assert [(g.name, g.server, g.access) for g in grants] == [
        ("get_account", "Northfield Core Banking", "read"),
        ("update_address", "Northfield Core Banking", "write"),
    ]
    assert grants[0].description == "get_account does a thing"
    assert grants[0].input_schema["required"] == ["id"]
