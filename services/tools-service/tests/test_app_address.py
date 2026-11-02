"""A custom app's base address and key come only from its connection (c-616 S4), by failure mode: a call goes to the
module's own copy of the address instead of the connection's; a tool addressed by its path alone cannot be made; a
module names a second base address beside its connection; and a sign-in key in an operation's header, typed or
referenced, competes with the connection that signs every call."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .fake_upstream import ENDPOINT, HOST
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

TEAM = {"X-Team-Id": "team_platform"}


async def connection(g: Gateway, base: str = ENDPOINT, key: str = "k-app") -> str:
    """The team's app: an API key in X-Api-Key, sent only to `base`."""
    made = (
        await g.client.post("/v1/connections", json={"name": "Ledger", "authKind": "api_key"}, headers=TEAM)
    ).json()["data"]
    fresh = (await g.client.get(f"/v1/connections/{made['id']}", headers=TEAM)).json()["data"]
    body = {
        "revision": fresh["revision"],
        "settings": {"name": "X-Api-Key", "baseUrl": base},
        "secretValues": {"key": key},
    }
    put = await g.client.put(f"/v1/connections/{made['id']}/environments/test", json=body, headers=TEAM)
    assert put.status_code == 200, put.text
    return str(made["id"])


async def run(g: Gateway, module: str, operation: str, args: dict[str, Any]) -> dict[str, Any]:
    body = {"operation": operation, "contextId": "owner", "target": "sandbox", "input": args, "environment": "test"}
    r = await g.client.post(f"/v1/tool-modules/{module}/test", json=body, headers=TEAM)
    assert r.status_code == 200, r.text
    return r.json()["data"]


def made_by_path(g: Gateway, conn: str, **extra: Any) -> dict[str, Any]:
    return {
        "name": f"ledger-{g.suffix}",
        "displayName": "Ledger",
        "system": "Ledger",
        "type": "http",
        "connectionId": conn,
        "http": {
            "name": f"read_account_{g.suffix}",
            "description": "Reads one account.",
            "access": "read",
            "method": "GET",
            "url": "/accounts/{accountId}",
        },
        **extra,
    }


async def test_a_call_goes_to_the_connections_address_not_the_modules_copy(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    store = ModuleStore(engine)
    m = await store.get(gateway.tenant, MODULE)
    assert m is not None
    conn = await connection(gateway)
    await store.put({**m, "connection_id": conn, "endpoint": f"https://{HOST}/old"}, expected_revision=m["revision"])
    out = await run(gateway, MODULE, gateway.tool("get_account"), {"accountId": "A"})
    assert out["decision"] == "allow", out
    sent = gateway.received[-1]
    assert (sent["path"], sent["headers"].get("x-api-key")) == ("/v1/accounts/A", "k-app")


async def test_a_tool_addressed_by_its_path_runs_on_the_connections_address(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    conn = await connection(gateway)
    r = await gateway.client.post("/v1/tool-modules", json=made_by_path(gateway, conn), headers=TEAM)
    assert r.status_code == 201, r.text
    # Published as review would publish it: a draft's Real run is refused, which is not what this is about.
    store = ModuleStore(engine)
    m = await store.get(gateway.tenant, r.json()["data"]["id"])
    assert m is not None and m["egress_hosts"] == [HOST], m
    await store.put({**m, "status": "published"}, expected_revision=m["revision"])
    out = await run(gateway, m["id"], f"read_account_{gateway.suffix}", {"accountId": "B"})
    assert out["decision"] == "allow", out
    sent = gateway.received[-1]
    assert (sent["path"], sent["headers"].get("x-api-key")) == ("/v1/accounts/B", "k-app")


async def test_a_second_base_address_beside_the_connection_is_refused(gateway: Gateway) -> None:  # noqa: F811
    conn = await connection(gateway)
    body = made_by_path(gateway, conn, endpoint="https://elsewhere.example")
    r = await gateway.client.post("/v1/tool-modules", json=body, headers=TEAM)
    assert r.status_code == 400 and "connection" in r.text.lower(), r.text


async def test_a_sign_in_header_is_refused_on_a_module_its_connection_signs(gateway: Gateway) -> None:  # noqa: F811
    conn = await connection(gateway)
    made = (await gateway.client.post("/v1/tool-modules", json=made_by_path(gateway, conn), headers=TEAM)).json()
    module = made["data"]
    op = module["operations"][0]["id"]
    for value in ("{{LEDGER_KEY}}", "Bearer {{LEDGER_KEY}}", "sk_test_literal"):
        r = await gateway.client.patch(
            f"/v1/tool-modules/{module['id']}/operations/{op}",
            json={"headers": [{"key": "X-Api-Key", "value": value}]},
            headers=TEAM,
        )
        assert r.status_code == 400 and "connection" in r.text.lower(), (value, r.text)


async def test_a_modules_answer_names_its_connections_base_address_per_environment(gateway: Gateway) -> None:  # noqa: F811
    # The tool page shows where a path goes (c-616): the module has no address of its own to show.
    conn = await connection(gateway)
    made = await gateway.client.post("/v1/tool-modules", json=made_by_path(gateway, conn), headers=TEAM)
    assert made.status_code == 201, made.text
    detail = (await gateway.client.get(f"/v1/tool-modules/{made.json()['data']['id']}", headers=TEAM)).json()["data"]
    assert detail["connection"]["baseUrls"] == {"test": ENDPOINT}, detail["connection"]


async def test_a_custom_app_starts_from_its_connection_with_no_type_or_address(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    # The New module dialog sends a connection and a name (c-616 group F); the kind follows the operations added.
    conn = await connection(gateway)
    body = {"displayName": "Ledger", "name": f"ledger-blank-{gateway.suffix}", "connectionId": conn}
    made = await gateway.client.post("/v1/tool-modules/blank", json=body, headers=TEAM)
    assert made.status_code == 201, made.text
    module = made.json()["data"]
    assert (module["type"], module["connection"]["id"]) == ("http", conn), module
    op = {"name": f"read_blank_{gateway.suffix}", "description": "Reads.", "access": "read", "method": "GET"}
    added = await gateway.client.post(
        f"/v1/tool-modules/{module['id']}/operations", json={**op, "url": "/accounts/{accountId}"}, headers=TEAM
    )
    assert added.status_code == 200, added.text
    store = ModuleStore(engine)
    m = await store.get(gateway.tenant, module["id"])
    assert m is not None and m["egress_hosts"] == [HOST], m
    await store.put({**m, "status": "published"}, expected_revision=m["revision"])
    out = await run(gateway, m["id"], op["name"], {"accountId": "C"})
    assert out["decision"] == "allow", out
    assert gateway.received[-1]["path"] == "/v1/accounts/C"


async def test_a_module_made_with_a_tool_needs_no_type(gateway: Gateway) -> None:  # noqa: F811
    conn = await connection(gateway)
    body = {k: v for k, v in made_by_path(gateway, conn).items() if k != "type"}
    r = await gateway.client.post("/v1/tool-modules", json=body, headers=TEAM)
    assert r.status_code == 201 and r.json()["data"]["type"] == "http", r.text
