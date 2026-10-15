"""GET /v1/internal/operations, what agents-service grants and hands a run from (c-048 G1), and GET /v1/tools/{name},
how many approvers a call needs, by failure mode: an operation that /v1/calls would refuse (hidden, unpublished,
drifted) offered to an agent, a model handed no usable input schema, another tenant's operations listed, a person
reading the internal list, and a registry operation's access class reported as unknown."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .conftest import Api, service_headers


async def grantable(api: Api, tenant: str | None = None) -> list[dict[str, Any]]:
    r = await api.client.get("/v1/internal/operations", headers=service_headers(tenant or api.tenant))
    assert r.status_code == 200, r.text
    return list(r.json()["data"])


async def callable_names(store: ModuleStore, tenant: str) -> set[str]:
    """What /v1/calls would run: enabled operations of published modules that have not drifted."""
    return {
        op["name"]
        for m in await store.all(tenant)
        if m["status"] == "published" and not m["drift"]
        for op in m["operations"]
        if op["enabled"]
    }


async def test_only_operations_the_gateway_would_run_are_offered(api: Api, engine: AsyncEngine) -> None:
    store = ModuleStore(engine)
    core = await store.get(api.tenant, "mod_core_banking")
    cards = await store.get(api.tenant, "mod_card_platform")
    assert core and cards and core["status"] == "published" and cards["status"] == "published"
    hidden = core["operations"][0]["name"]
    ops = [{**o, "enabled": o["name"] != hidden} for o in core["operations"]]
    await store.put({**core, "operations": ops}, expected_revision=core["revision"])
    await store.put({**cards, "drift": True}, expected_revision=cards["revision"])

    names = {o["name"] for o in await grantable(api)}

    assert names == await callable_names(store, api.tenant)
    assert hidden not in names
    assert not names & {o["name"] for o in cards["operations"]}
    in_review = [m for m in await store.all(api.tenant) if m["status"] != "published"]
    assert in_review and not names & {o["name"] for m in in_review for o in m["operations"]}


async def test_each_operation_carries_a_json_schema_for_its_input(api: Api) -> None:
    by_name = {o["name"]: o for o in await grantable(api)}
    profile = by_name["get_customer_profile"]
    assert profile["description"] == "Name, contact details and products held by a customer"
    assert profile["access"] == "read" and profile["requiresApproval"] is False
    assert profile["moduleId"] == "mod_core_banking"
    assert profile["inputSchema"] == {
        "type": "object",
        "properties": {"customerId": {"type": "string", "description": "Customer number", "examples": ["CUS-118842"]}},
        "required": ["customerId"],
        "additionalProperties": False,
    }
    assert by_name["send_reply"]["requiresApproval"] is True


async def test_another_tenants_operations_are_not_listed(api: Api) -> None:
    assert await grantable(api)
    assert await grantable(api, "tenant_nobody_seeded") == []


async def test_the_list_is_internal(api: Api) -> None:
    r = await api.client.get("/v1/internal/operations", headers={"X-Dev-User": "Maya Okafor"})
    assert r.status_code == 401, r.text


async def test_a_registry_operations_access_class_is_known(api: Api) -> None:
    r = await api.client.get("/v1/tools/update_address", headers=service_headers(api.tenant))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert (data["name"], data["access"]) == ("update_address", "write")
    assert data["approval"]["approvers"] == 1 and data["approval"]["selfApproval"] is False
    missing = await api.client.get("/v1/tools/no_such_tool", headers=service_headers(api.tenant))
    assert missing.status_code == 404
