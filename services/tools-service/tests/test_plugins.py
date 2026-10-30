"""Plugins in tools-service (c-564), by failure mode: team A's call uses team B's connection, instance or egress hosts,
because the plugin is one workspace-level module; a team sees or calls a plugin it never turned on, or one the platform
admin turned off; a team's setting beats a field the platform admin locked; a token naming a host outside the system
points every call there; one team's calls spend another team's rate window; a Python tool reaches a host the plugin
does not list; and a caller forges a next-page address that the team's token is then sent to."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

import ops_tools.registry as reg
from ops_identity import ActingForPerson
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.loader import Loaded
from ops_plugin_sdk.manifest import SIGN_IN_KINDS
from ops_service_kit.settings import Settings
from ops_tools.auth.kinds import BY_ID
from ops_tools.executor import HttpExecutor
from ops_tools.graph_mailbox import CursorSeal
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.registry import ToolRegistry
from ops_tools.store.connections import SHARED
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .plugin_desk import plugin as desk
from .test_personal_sign_in import JAMES, MAYA, TEAM, connection, rig

ID = "test.desk"


class Policy:
    """The platform's `plugins` policy as GET /v1/policies/plugins answers it."""

    def __init__(self, value: dict[str, Any]) -> None:
        self.value = value

    async def get(self, path: str, *, tenant: str) -> Any:
        assert path == "/v1/policies/plugins"
        return {"value": self.value}


def host(engine: AsyncEngine, store: ModuleStore, value: dict[str, Any] | None = None) -> PluginHost:
    switches = InstallSwitches(Policy(value if value is not None else {ID: {"enabled": True}}))
    return PluginHost(store, PluginBindings(engine), switches, [Loaded("desk", desk, None)])


async def bind(engine: AsyncEngine, tenant: str, team: str, instance: str, conn: str, *, on: bool = True) -> None:
    await PluginBindings(engine).put(
        tenant, team, ID, enabled=on, connection_id=conn, settings={"instance_url": instance}, by="test"
    )


async def test_each_team_calls_with_its_own_connection_instance_and_hosts(
    local_catalog: Any, engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    h = host(engine, store)
    registry = ToolRegistry(local_catalog, store, h)
    await bind(engine, tenant, "team_a", "https://alpha.my.desk.test", "con_a")
    await bind(engine, tenant, "team_b", "https://beta.my.desk.test", "con_b")
    a = await registry.resolve("desk_get_case", tenant_id=tenant, team_id="team_a")
    b = await registry.resolve("desk_get_case", tenant_id=tenant, team_id="team_b")
    assert a is not None and a.module is not None and b is not None and b.module is not None
    assert (a.module["connection_id"], a.module["endpoint"], a.module["egress_hosts"]) == (
        "con_a",
        "https://alpha.my.desk.test/api/v1",
        ["alpha.my.desk.test"],
    )
    assert (b.module["connection_id"], b.module["endpoint"], b.module["egress_hosts"]) == (
        "con_b",
        "https://beta.my.desk.test/api/v1",
        ["beta.my.desk.test"],
    )
    # The stored module holds none of a team's parts.
    stored = await store.get(tenant, "mod_plugin_desk")
    assert stored is not None and stored["connection_id"] is None and stored["team_id"] is None
    # Each team spends its own rate window.
    assert a.operation is not None and b.operation is not None
    assert a.operation["rate_key"] != b.operation["rate_key"]


async def test_a_plugin_is_off_unless_both_switches_are_on(
    local_catalog: Any, engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    await bind(engine, tenant, "team_a", "https://alpha.my.desk.test", "con_a")
    await bind(engine, tenant, "team_off", "https://gamma.my.desk.test", "con_c", on=False)
    on = ToolRegistry(local_catalog, store, host(engine, store))
    for team, why in (("team_none", "off for this team"), ("team_off", "off for this team")):
        r = await on.resolve("desk_get_case", tenant_id=tenant, team_id=team)
        assert r is not None and r.module is not None and why in str(r.module.get("plugin_off")), (team, r)
    assert (await on.resolve("desk_get_case", tenant_id=tenant, team_id="team_a")).module.get("plugin_off") is None  # type: ignore[union-attr]
    install_off = ToolRegistry(local_catalog, store, host(engine, store, {ID: {"enabled": False}}))
    r = await install_off.resolve("desk_get_case", tenant_id=tenant, team_id="team_a")
    assert r is not None and r.module is not None and "off for this install" in str(r.module["plugin_off"])


async def test_a_team_without_the_plugin_does_not_list_its_tools(
    local_catalog: Any, engine: AsyncEngine, store: ModuleStore, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    await bind(engine, tenant, "team_a", "https://alpha.my.desk.test", "con_a")
    registry = ToolRegistry(local_catalog, store, host(engine, store))
    monkeypatch.setattr(reg, "acting_team", lambda: "team_a")
    assert "desk_get_case" in {t["name"] for t in await registry.grantable(tenant)}
    monkeypatch.setattr(reg, "acting_team", lambda: "team_none")
    assert "desk_get_case" not in {t["name"] for t in await registry.grantable(tenant)}


async def test_a_plugins_tools_are_not_grantable_once_plugins_are_switched_off(
    local_catalog: Any, engine: AsyncEngine, store: ModuleStore, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A service started once with OPS_PLUGINS on keeps the plugin's module; started again with it off, an agent must
    # not be granted tools no call can run.
    await bind(engine, tenant, "team_a", "https://alpha.my.desk.test", "con_a")
    monkeypatch.setattr(reg, "acting_team", lambda: "team_a")
    assert "desk_get_case" in {
        t["name"] for t in await ToolRegistry(local_catalog, store, host(engine, store)).grantable(tenant)
    }
    off = ToolRegistry(local_catalog, store, None)
    assert "desk_get_case" not in {t["name"] for t in await off.grantable(tenant)}
    assert "desk_get_case" not in {t["name"] for t in await off.grantable(tenant, lambda _: True)}


async def test_a_locked_field_wins_over_the_team(engine: AsyncEngine, store: ModuleStore, tenant: str) -> None:
    h = host(engine, store, {ID: {"enabled": True, "locked": {"api_version": "9"}}})
    merged = await h.settings(tenant, desk, {"api_version": "2", "instance_url": "https://a.my.desk.test"})
    assert merged["api_version"] == "9"


async def test_the_instance_comes_from_the_token_and_only_from_the_systems_hosts(
    engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    h = host(engine, store)
    await PluginBindings(engine).put(tenant, "team_a", ID, enabled=True, connection_id="con_a", settings={}, by="t")
    with pytest.raises(ValueError, match=r"takes only a host under \.my\.desk\.test"):
        await h.on_token(tenant, "con_a", {"access_token": "x", "instance_url": "https://evil.example"})
    extra = await h.on_token(tenant, "con_a", {"access_token": "x", "instance_url": "https://alpha.my.desk.test/"})
    assert extra == {"baseUrl": "https://alpha.my.desk.test", "testPath": "/api/v1/limits"}
    b = await PluginBindings(engine).get(tenant, "team_a", ID)
    assert b is not None and b["settings"]["instance_url"] == "https://alpha.my.desk.test"


class AllowAll:
    async def check_url(self, tenant_id: str, url: str) -> None:
        return None


def plugin_executor(engine: AsyncEngine, store: ModuleStore, seen: list[str]) -> PluginExecutor:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        page = 2 if "page=2" in str(request.url) else 1
        return httpx.Response(
            200, json={"items": [{"id": f"t{page}", "updated_at": "2026-10-29T00:00:00Z", "title": "T"}]}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    return PluginExecutor(host(engine, store), HttpExecutor(client, AllowAll()), b"k" * 32)  # type: ignore[arg-type]


def module_for(tenant: str) -> dict[str, Any]:
    return {
        "tenant_id": tenant,
        "id": "mod_plugin_desk",
        "display_name": "Desk",
        "template_id": "plugin:test.desk",
        "connection_id": "con_a",
        "egress_hosts": ["alpha.my.desk.test"],
        "plugin_settings": {"instance_url": "https://alpha.my.desk.test", "api_version": "1"},
    }


async def test_a_python_tool_reaches_only_the_plugins_hosts(
    engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    seen: list[str] = []
    out = await plugin_executor(engine, store, seen).run(
        module_for(tenant), {"name": "desk_reach_out"}, {}, actor="t", environment=None, acting_for=None
    )
    assert not out.ok and out.output["error"]["code"] == "EGRESS_DENIED", out
    assert seen == []


async def test_a_listing_cursor_is_sealed_and_a_forged_one_refused(
    engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    seen: list[str] = []
    ex = plugin_executor(engine, store, seen)
    m, op = module_for(tenant), {"name": "desk_list_things"}
    first = await ex.run(m, op, {}, actor="t", environment=None, acting_for=None)
    sealed = first.output["next_cursor"]
    assert first.ok and sealed != "/things?page=2" and "page=2" not in sealed
    second = await ex.run(m, op, {"cursor": sealed}, actor="t", environment=None, acting_for=None)
    assert second.ok and second.output["items"][0]["id"] == "t2"
    forged = CursorSeal(b"k" * 32, tenant, "con_b", "desk_list_things").close("/things?page=2")
    refused = await ex.run(m, op, {"cursor": forged}, actor="t", environment=None, acting_for=None)
    assert not refused.ok and refused.output["error"]["code"] == "INVALID_INPUT", refused
    assert len(seen) == 2


def test_the_sdk_knows_the_platforms_sign_in_kinds() -> None:
    assert set(SIGN_IN_KINDS) == set(BY_ID)


def test_the_test_plugin_is_a_plugin() -> None:
    assert isinstance(desk, Plugin) and desk.manifest.id == ID
    _ = ActingForPerson


def test_nothing_is_read_unless_plugins_are_switched_on(engine: AsyncEngine, store: ModuleStore) -> None:
    # OPS_PLUGINS is off until the plugins release: an installed or a developer's plugin must stay unread.
    folder = str(Path(__file__).parent / "plugin_desk")
    parts = (store, PluginBindings(engine), InstallSwitches(None))
    assert PluginHost.when_on(Settings(plugins=False, plugin_paths=[folder]), *parts) is None
    on = PluginHost.when_on(Settings(plugins=True, plugin_paths=[folder]), *parts)
    assert on is not None and "test.desk" in on.plugins


async def test_a_python_tool_signs_in_as_the_person_it_acts_for(
    engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    # A plugin connection set to each person's own account: a call for James carries James's token, never Maya's or
    # the team's, and a call with nobody behind it is refused before anything is sent.
    connections, tokens, auth = rig(engine)
    conn = await connection(connections, tenant, "person")
    for who, token in ((SHARED, "at-team"), (JAMES.sub, "at-james"), (MAYA.sub, "at-maya")):
        await tokens.store_answer(tenant, conn, "test", {"access_token": token, "expires_in": 3600}, who)
    heard: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        heard.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"items": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    ex = PluginExecutor(host(engine, store), HttpExecutor(client, AllowAll(), None, auth), b"k" * 32)  # type: ignore[arg-type]
    m = {
        **module_for(tenant),
        "team_id": TEAM,
        "connection_id": conn,
        "endpoint": "https://crm.bank.test",
        "egress_hosts": ["crm.bank.test"],
        "plugin_settings": {"instance_url": "https://crm.bank.test", "api_version": "1"},
    }
    op = {"name": "desk_list_things"}
    for who in (JAMES, MAYA):
        out = await ex.run(m, op, {}, actor="t", environment="test", acting_for=who)
        assert out.ok, out
    assert heard == ["Bearer at-james", "Bearer at-maya"]
    nobody = await ex.run(m, op, {}, actor="t", environment="test", acting_for=None)
    assert not nobody.ok and nobody.output["error"]["code"] == "CONNECTION_NOT_LINKED", nobody
    assert len(heard) == 2


async def test_another_teams_connection_never_serves_a_teams_call(
    engine: AsyncEngine, store: ModuleStore, tenant: str
) -> None:
    # Team B's binding names team A's connection (a stale or forged row): the call is refused and nothing is sent,
    # because for the call the plugin's module belongs to the calling team and a connection serves only its own team.
    connections, tokens, auth = rig(engine)
    team_a_conn = await connection(connections, tenant, "team")
    await tokens.store_answer(tenant, team_a_conn, "test", {"access_token": "at-team-a", "expires_in": 3600})
    await bind(engine, tenant, "team_b", "https://crm.bank.test", team_a_conn)
    heard: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        heard.append(request.headers.get("authorization"))
        return httpx.Response(200, json={"items": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    h = host(engine, store)
    ex = PluginExecutor(h, HttpExecutor(client, AllowAll(), None, auth), b"k" * 32)  # type: ignore[arg-type]
    m = await h.for_call(tenant, "team_b", {**module_for(tenant), "team_id": None})
    lee = ActingForPerson(sub="usr_lee", email="lee@bank.example", name="Lee", team_id="team_b")
    out = await ex.run(m, {"name": "desk_list_things"}, {}, actor="t", environment="test", acting_for=lee)
    assert not out.ok and heard == [], (out, heard)
