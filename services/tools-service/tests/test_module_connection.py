"""Every custom module's address lives on a connection (c-616 D3b-2a), by failure mode: a module made from a full URL
with no connection keeps its address only on itself, so dropping the module's copy strands it; a blank module's first
tool sets the module's address but not its connection's; an app that needs no sign-in reads "not signed in" forever,
since it has no token and nothing to test; and the migration gives a connection to a plugin's system module, or its
downgrade leaves the connections it made; or it gives one to a built-in app's module, which then stops showing as the
built-in app."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_tools.connections.records import CONNECTED, REVOKED, account_state
from ops_tools.modules.seed import blank
from ops_tools.store.modules import ModuleStore

from .fake_upstream import HOST
from .test_app_address import run
from .test_calls import Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

TEAM = {"X-Team-Id": "team_platform"}
ORIGIN = f"https://{HOST}"
BEFORE = "tools_0055_secret_isolation"
MODULE_CONNECTIONS = "tools_0056_module_connections"
BEFORE_ADDRESS = "tools_0057_connection_isolation"


async def legacy_module(engine: AsyncEngine, module_id: str, kind: str | None, endpoint: str = "", **more: Any) -> None:
    """A module row written in SQL: as the schema before tools_0058 held it (its own endpoint and type), or after it
    when `kind` is None."""
    m = blank(
        module_id=module_id, tenant_id="t_mc", team_id="team_ops", owner="Operations", me="t", at=datetime.now(UTC),
        input={"displayName": module_id, "name": module_id.replace("_", "-")},
    )  # fmt: skip
    row = {k: v for k, v in m.items() if k not in ("operations", "versions", "approvals", "egress_hosts")}
    row |= ({"endpoint": endpoint, "type": kind} if kind else {}) | {"revision": 1, **more}
    cols: list[sa.ColumnClause[Any]] = [
        sa.column(k, sa.JSON) if isinstance(v, dict | list) else sa.column(k) for k, v in row.items()
    ]
    async with engine.begin() as c:
        await c.execute(sa.insert(sa.table("tool_modules", *cols)).values(**row))


async def legacy_connection(
    engine: AsyncEngine, connection_id: str, kind: str, envs: dict[str, Any], *, name: str = "", by: str = "t"
) -> None:
    now = datetime.now(UTC)
    async with engine.begin() as c:
        await c.execute(
            sa.text(
                "insert into connections (tenant_id, id, team_id, name, auth_kind, status, revision, created_by, "
                "created_at, updated_by, updated_at) values ('t_mc', :id, 'team_ops', :name, :kind, 'healthy', 1, :by, "
                ":at, 't', :at)"
            ),
            {"id": connection_id, "name": name or connection_id, "kind": kind, "by": by, "at": now},
        )
        for env, settings in envs.items():
            await c.execute(
                sa.text(
                    "insert into connection_environments (tenant_id, connection_id, environment, team_id, settings, "
                    "secrets, updated_by, updated_at) values ('t_mc', :id, :env, 'team_ops', cast(:s as json), "
                    "cast('{}' as json), 't', :at)"
                ),
                {"id": connection_id, "env": env, "s": json.dumps(settings), "at": now},
            )


def tool(g: Gateway, url: str) -> dict[str, Any]:
    return {
        "name": f"read_account_{g.suffix}",
        "description": "Reads one account.",
        "access": "read",
        "method": "GET",
        "url": url,
    }


async def detail(g: Gateway, module_id: str) -> dict[str, Any]:
    return (await g.client.get(f"/v1/tool-modules/{module_id}", headers=TEAM)).json()["data"]


async def connection(g: Gateway, connection_id: str) -> dict[str, Any]:
    return (await g.client.get(f"/v1/apps/{connection_id}/accounts/{connection_id}", headers=TEAM)).json()["data"]


async def published(engine: AsyncEngine, g: Gateway, module_id: str) -> None:
    # As review would publish it: a draft's Real run is refused, which is not what this is about.
    store = ModuleStore(engine)
    m = await store.get(g.tenant, module_id)
    assert m is not None
    await store.put({**m, "status": "published"}, expected_revision=m["revision"])


async def test_a_module_made_from_a_full_url_gets_a_connection_holding_its_address(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    op = tool(gateway, f"{ORIGIN}/v1/accounts/{{accountId}}")
    body = {"name": f"ledger-open-{gateway.suffix}", "displayName": "Ledger", "system": "Ledger", "http": op}
    made = await gateway.client.post("/v1/tool-modules", json=body, headers=TEAM)
    assert made.status_code == 201, made.text
    module = await detail(gateway, made.json()["data"]["id"])
    assert module["connection"]["baseUrl"] == ORIGIN, module["connection"]
    assert (await connection(gateway, module["connection"]["id"]))["authKind"] == "none"
    await published(engine, gateway, module["id"])
    out = await run(gateway, module["id"], op["name"], {"accountId": "D"})
    assert out["decision"] == "allow", out
    assert gateway.received[-1]["path"] == "/v1/accounts/D"


async def test_a_blank_modules_first_tool_makes_the_connection_its_address_lives_on(
    gateway: Gateway,  # noqa: F811
    engine: AsyncEngine,
) -> None:
    # A blank module has no kind until its first tool (c-616): a code module must never get an empty app.
    body = {"displayName": "Ledger", "name": f"ledger-empty-{gateway.suffix}"}
    made = await gateway.client.post("/v1/tool-modules/blank", json=body, headers=TEAM)
    assert made.status_code == 201, made.text
    module = made.json()["data"]
    assert module["connection"] is None, module["connection"]
    op = tool(gateway, f"{ORIGIN}/v1/accounts/{{accountId}}")
    added = await gateway.client.post(f"/v1/tool-modules/{module['id']}/operations", json=op, headers=TEAM)
    assert added.status_code == 200, added.text
    after = await detail(gateway, module["id"])
    assert after["connection"]["baseUrl"] == ORIGIN, after["connection"]
    await published(engine, gateway, module["id"])
    out = await run(gateway, module["id"], op["name"], {"accountId": "E"})
    assert out["decision"] == "allow", out
    assert gateway.received[-1]["path"] == "/v1/accounts/E"


def test_an_app_that_needs_no_sign_in_reads_connected_until_revoked() -> None:
    now = datetime.now(UTC)
    open_app: dict[str, Any] = {"auth_kind": "none", "status": "draft"}
    assert account_state(open_app, None, now) == CONNECTED
    assert account_state({**open_app, "status": REVOKED}, None, now) == REVOKED
    assert account_state({**open_app, "auth_kind": "api_key"}, None, now) != CONNECTED


async def test_the_migration_moves_each_custom_modules_address_onto_a_connection_and_back() -> None:
    async with scratch_database("tools_module_connections") as target:
        _alembic(target, "upgrade", BEFORE)
        engine = create_async_engine(target)
        try:
            await legacy_module(engine, "mod_ledger", "http", f"{ORIGIN}/v1")
            await legacy_module(engine, "mod_cases", "mcp", "https://cases.test/mcp")
            await legacy_module(
                engine, "mod_plugin_desk", "http", "{instance}/api", team_id=None, template_id="plugin:desk"
            )
            await legacy_module(engine, "mod_knowledge", "mcp", "https://kb.test/mcp", name="knowledge-search")
            _alembic(target, "upgrade", MODULE_CONNECTIONS)
            query = (
                "select m.id, c.auth_kind, e.environment, e.settings from tool_modules m "
                "left join connections c on c.tenant_id = m.tenant_id and c.id = m.connection_id "
                "left join connection_environments e on e.tenant_id = c.tenant_id and e.connection_id = c.id "
                "order by m.id, e.environment"
            )
            async with engine.connect() as c:
                rows = [tuple(r) for r in (await c.execute(sa.text(query))).all()]
            assert rows == [
                ("mod_cases", "none", "production", {"baseUrl": "https://cases.test/mcp"}),
                ("mod_cases", "none", "test", {"baseUrl": "https://cases.test/mcp"}),
                ("mod_knowledge", None, None, None),
                ("mod_ledger", "none", "production", {"baseUrl": f"{ORIGIN}/v1"}),
                ("mod_ledger", "none", "test", {"baseUrl": f"{ORIGIN}/v1"}),
                ("mod_plugin_desk", None, None, None),
            ], rows
            _alembic(target, "downgrade", BEFORE)
            async with engine.connect() as c:
                linked = (
                    await c.execute(sa.text("select count(*) from tool_modules where connection_id is not null"))
                ).scalar()
                left = (await c.execute(sa.text("select count(*) from connections"))).scalar()
                envs = (await c.execute(sa.text("select count(*) from connection_environments"))).scalar()
            assert (linked, left, envs) == (0, 0, 0)
        finally:
            await engine.dispose()


async def test_a_sign_in_header_is_refused_on_a_module_with_no_app_of_its_own(gateway: Gateway) -> None:  # noqa: F811
    # Its open connection is where the key goes (c-616 D3b-2b): a header key would be a second home for sign-in.
    op = {**tool(gateway, f"{ORIGIN}/v1/accounts/{{accountId}}"), "headers": [{"key": "X-Api-Key", "value": "{{K}}"}]}
    body = {"name": f"ledger-keyed-{gateway.suffix}", "displayName": "Ledger", "system": "Ledger", "http": op}
    made = await gateway.client.post("/v1/tool-modules", json=body, headers=TEAM)
    assert made.status_code == 400 and "connection" in made.text.lower(), made.text
    blank_body = {"displayName": "Ledger", "name": f"ledger-keyed-blank-{gateway.suffix}"}
    module = (await gateway.client.post("/v1/tool-modules/blank", json=blank_body, headers=TEAM)).json()["data"]
    added = await gateway.client.post(f"/v1/tool-modules/{module['id']}/operations", json=op, headers=TEAM)
    assert added.status_code == 400 and "connection" in added.text.lower(), added.text


async def test_tools_0058_moves_each_modules_address_onto_its_connection_and_back() -> None:
    async with scratch_database("tools_module_address") as target:
        _alembic(target, "upgrade", BEFORE_ADDRESS)
        engine = create_async_engine(target)
        try:
            await legacy_connection(engine, "con_keyed", "api_key", {"test": {"name": "X-Api-Key"}})
            await legacy_connection(engine, "con_demo", "bearer", {})
            await legacy_connection(engine, "con_open", "none", {"production": {"baseUrl": "https://open.test"}})
            await legacy_module(engine, "mod_keyed", "http", "https://keyed.test/v1", connection_id="con_keyed")
            await legacy_module(engine, "mod_demo", "mcp", "https://demo.test/mcp", connection_id="con_demo")
            await legacy_module(engine, "mod_open", "http", "https://open.test", connection_id="con_open")
            _alembic(target, "upgrade", "tools_0058_module_address")
            query = "select connection_id, environment, settings from connection_environments order by 1, 2"
            async with engine.connect() as c:
                envs = [tuple(r) for r in (await c.execute(sa.text(query))).all()]
                columns = {
                    str(r[0])
                    for r in await c.execute(
                        sa.text("select column_name from information_schema.columns where table_name = 'tool_modules'")
                    )
                }
            assert envs == [
                ("con_demo", "test", {"baseUrl": "https://demo.test/mcp"}),
                ("con_keyed", "test", {"name": "X-Api-Key", "baseUrl": "https://keyed.test/v1"}),
                ("con_open", "production", {"baseUrl": "https://open.test"}),
            ], envs
            assert not {"endpoint", "type"} & columns
            _alembic(target, "downgrade", BEFORE_ADDRESS)
            async with engine.connect() as c:
                back = [
                    tuple(r)
                    for r in await c.execute(sa.text("select id, endpoint, type from tool_modules order by id"))
                ]
                demo = (
                    await c.execute(
                        sa.text("select count(*) from connection_environments where connection_id = 'con_demo'")
                    )
                ).scalar()
            assert back == [
                ("mod_demo", "https://demo.test/mcp", "http"),
                ("mod_keyed", "https://keyed.test/v1", "http"),
                ("mod_open", "https://open.test", "http"),
            ], back
            assert demo == 0, "the demo connection's filled test row goes with the downgrade"
        finally:
            await engine.dispose()


async def test_tools_0058_stops_when_one_connection_serves_two_addresses() -> None:
    async with scratch_database("tools_module_address_two") as target:
        _alembic(target, "upgrade", BEFORE_ADDRESS)
        engine = create_async_engine(target)
        try:
            await legacy_connection(engine, "con_shared", "none", {})
            await legacy_module(engine, "mod_a", "http", "https://a.test", connection_id="con_shared")
            await legacy_module(engine, "mod_b", "http", "https://b.test", connection_id="con_shared")
            try:
                _alembic(target, "upgrade", "tools_0058_module_address")
            except subprocess.CalledProcessError as e:
                assert b"different addresses" in e.stderr, e.stderr[-400:]
            else:
                raise AssertionError("the upgrade ran with one connection serving two addresses")
        finally:
            await engine.dispose()


async def test_tools_0059_marks_the_connections_made_for_a_tool_and_only_those() -> None:
    async with scratch_database("tools_connection_origin") as target:
        _alembic(target, "upgrade", "tools_0058_module_address")
        engine = create_async_engine(target)
        try:
            await legacy_connection(engine, "con_moved", "none", {}, by="module address")
            await legacy_connection(engine, "con_mod_seeded", "none", {})
            await legacy_connection(engine, "con_page", "none", {}, name="Rates")
            await legacy_connection(engine, "con_added", "none", {}, name="Ledger")
            await legacy_connection(engine, "con_keyed", "api_key", {}, name="Keyed")
            await legacy_connection(engine, "int_demo", "none", {}, name="Demo", by="seed")
            await legacy_module(engine, "mod_rates", None, connection_id="con_page", display_name="Rates")
            await legacy_module(engine, "mod_ledger_a", None, connection_id="con_added", display_name="Ledger A")
            await legacy_module(engine, "mod_keyed", None, connection_id="con_keyed", display_name="Keyed")
            await legacy_module(engine, "mod_demo", None, connection_id="int_demo", display_name="Demo")
            _alembic(target, "upgrade", "tools_0059_connection_origin")
            async with engine.connect() as c:
                origins = dict((await c.execute(sa.text("select id, origin from connections"))).all())
            assert origins == {
                "con_moved": "tool", "con_mod_seeded": "tool", "con_page": "tool", "con_added": None, "con_keyed": None,
                "int_demo": None,
            }, origins  # fmt: skip
            _alembic(target, "downgrade", "tools_0058_module_address")
        finally:
            await engine.dispose()
