"""A tool's sign-in header moves onto its module's connection at start (c-616 D3b-2b), by failure mode: the key is
guessed for a module whose tools disagree; a moved module sends its key twice, or not at all; the published copy calls
run still carries the header; a dry run writes; and a tool left alone gives no sign that it still sends a key."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.header_keys import move_header_keys
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore

from .fake_upstream import HOST
from .test_app_address import run
from .test_calls import Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

TEAM = {"X-Team-Id": "team_platform"}


async def keyed_module(g: Gateway, engine: AsyncEngine, *headers: dict[str, str]) -> dict[str, Any]:
    """A published module on its own open connection whose tools carry `headers`, one per tool, as a module saved
    before sign-in headers were refused holds them, its published copy included."""
    ops = [
        {"name": f"read_{n}_{g.suffix}", "description": "Reads.", "access": "read", "method": "GET",
         "url": f"https://{HOST}/v1/accounts/{{accountId}}"}
        for n in range(len(headers))
    ]  # fmt: skip
    body = {"name": f"keyed-{g.suffix}", "displayName": "Keyed", "system": "Keyed", "http": ops[0]}
    made = await g.client.post("/v1/tool-modules", json=body, headers=TEAM)
    assert made.status_code == 201, made.text
    module_id = made.json()["data"]["id"]
    for op in ops[1:]:
        added = await g.client.post(f"/v1/tool-modules/{module_id}/operations", json=op, headers=TEAM)
        assert added.status_code == 200, added.text
    store = ModuleStore(engine)
    m = await store.get(g.tenant, module_id)
    assert m is not None
    m["operations"] = [{**o, "headers": [h]} for o, h in zip(m["operations"], headers, strict=True)]
    await store.put({**m, "status": "published", "baseline": m["operations"]}, expected_revision=m["revision"])
    return await store.get(g.tenant, module_id) or {}


async def secret(g: Gateway, name: str, value: str) -> None:
    r = await g.client.post("/v1/secrets", json={"name": name, "value": value}, headers=TEAM)
    assert r.status_code == 201, r.text


async def move(engine: AsyncEngine, g: Gateway, *, dry_run: bool = False) -> list[tuple[str, str]]:
    return await move_header_keys(ModuleStore(engine), ConnectionStore(engine), dry_run=dry_run, tenant_id=g.tenant)


async def connection(g: Gateway, connection_id: str) -> dict[str, Any]:
    return (await g.client.get(f"/v1/connections/{connection_id}", headers=TEAM)).json()["data"]


async def test_an_api_key_header_moves_and_the_call_sends_it_once_from_the_connection(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    name = f"LEDGER_KEY_{gateway.suffix.upper()}"
    m = await keyed_module(gateway, engine, {"key": "X-Api-Key", "value": f"{{{{{name}}}}}"})
    await secret(gateway, name, "k-moved")
    assert await move(engine, gateway) == [(gateway.tenant, m["id"])]
    after = await ModuleStore(engine).get(gateway.tenant, m["id"]) or {}
    assert after["operations"][0]["headers"] == [] and after["baseline"][0]["headers"] == [], after["baseline"]
    assert (await connection(gateway, m["connection_id"]))["authKind"] == "api_key"
    out = await run(gateway, m["id"], m["operations"][0]["name"], {"accountId": "M1"})
    assert out["decision"] == "allow", out
    sent = gateway.received[-1]["headers"]
    assert [k for k in sent if k.lower() == "x-api-key"] == ["x-api-key"] and sent["x-api-key"] == "k-moved", sent
    assert await move(engine, gateway) == [], "a moved module has nothing left to move"


async def test_a_bearer_header_moves_to_a_bearer_connection(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    name = f"LEDGER_TOKEN_{gateway.suffix.upper()}"
    m = await keyed_module(gateway, engine, {"key": "Authorization", "value": f"Bearer {{{{{name}}}}}"})
    await secret(gateway, name, "t-moved")
    await move(engine, gateway)
    assert (await connection(gateway, m["connection_id"]))["authKind"] == "bearer"
    out = await run(gateway, m["id"], m["operations"][0]["name"], {"accountId": "M2"})
    assert out["decision"] == "allow", out
    assert gateway.received[-1]["headers"]["authorization"] == "Bearer t-moved"


async def test_tools_that_disagree_are_left_and_their_page_says_so(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    m = await keyed_module(
        gateway, engine, {"key": "X-Api-Key", "value": "{{ONE_KEY}}"}, {"key": "X-Api-Key", "value": "{{OTHER_KEY}}"}
    )
    assert await move(engine, gateway) == []
    assert (await connection(gateway, m["connection_id"]))["authKind"] == "none"
    page = (await gateway.client.get(f"/v1/tool-modules/{m['id']}", headers=TEAM)).json()["data"]
    assert [o["signInHeader"] for o in page["operations"]] == ["X-Api-Key", "X-Api-Key"], page["operations"]


async def test_a_dry_run_names_the_move_and_writes_nothing(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    m = await keyed_module(gateway, engine, {"key": "X-Api-Key", "value": "{{DRY_KEY}}"})
    assert await move(engine, gateway, dry_run=True) == [(gateway.tenant, m["id"])]
    after = await ModuleStore(engine).get(gateway.tenant, m["id"]) or {}
    assert after["operations"][0]["headers"] == [{"key": "X-Api-Key", "value": "{{DRY_KEY}}"}]
    assert (await connection(gateway, m["connection_id"]))["authKind"] == "none"
