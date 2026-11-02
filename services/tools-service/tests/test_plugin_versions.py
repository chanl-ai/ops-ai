"""Each team's plugin version (c-609), by failure mode: a turn-on or settings save wipes the version a team took, a
take lands on a team with no binding, or the stamp cannot find another team's binding of the same plugin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk import Plugin
from ops_plugin_sdk.loader import Loaded, discover
from ops_plugin_sdk.manifest import read
from ops_service_kit.settings import Settings
from ops_store.team_scope import acting_as
from ops_tools.auth import Prepared
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.service import ConnectionService
from ops_tools.executor import HttpExecutor
from ops_tools.gateway_calls import _before_policy  # pyright: ignore[reportPrivateUsage]
from ops_tools.modules.directory import Directory
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.registry import ToolRegistry
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .test_plugins import AllowAll, Policy
from .test_review_decisions import introspect, jwks, person

ID = "test.fields"
DECL: dict[str, Any] = {"version": "0.1.0", "headers": {}, "tools": [{"name": "search", "access": "read"}]}


async def test_a_save_keeps_the_version_a_team_took_and_a_take_needs_a_binding(
    engine: AsyncEngine, tenant: str
) -> None:
    b = PluginBindings(engine)
    assert not await b.take(tenant, "team_ops", ID, version="0.1.0", digest="d1", declarations=DECL)
    await b.put(tenant, "team_ops", ID, enabled=True, connection_id=None, settings={}, by="t")
    assert await b.take(tenant, "team_ops", ID, version="0.1.0", digest="d1", declarations=DECL)
    await b.put(tenant, "team_ops", ID, enabled=True, connection_id="con_a", settings={"x": 1}, by="t")
    row = await b.get(tenant, "team_ops", ID)
    assert row is not None and (row["version"], row["digest"], row["declarations"]) == ("0.1.0", "d1", DECL)


async def test_every_teams_binding_of_a_plugin_is_found_for_the_stamp(engine: AsyncEngine, tenant: str) -> None:
    b = PluginBindings(engine)
    for team in ("team_ops", "team_platform"):
        await b.put(tenant, team, ID, enabled=True, connection_id=None, settings={}, by="t")
    await b.put(tenant, "team_ops", "test.other", enabled=True, connection_id=None, settings={}, by="t")
    assert sorted(r["team_id"] for r in await b.of_plugin(tenant, ID)) == ["team_ops", "team_platform"]


# Calls and lists run each team's version across an upgrade (c-609 T003).

V1 = Path(__file__).parent / "plugin_fields" / "fields_desk"
V2 = Path(__file__).parent / "plugin_versions" / "fields_desk" / "plugin.yaml"
TOKEN = "team-token-41c7"


class TeamSignIn:
    async def prepare(self, *_: Any, **__: Any) -> Prepared:
        return Prepared("con_a", "production", headers={"Authorization": f"Bearer {TOKEN}"}, values=[TOKEN])


class Upgrade:
    """One account with two teams on 0.1.0, then the operator installs 0.2.0 (a new process, a new host). The 0.2.0
    plugin is built in memory from its manifest: one process cannot import two packages named fields_desk."""

    def __init__(self, engine: AsyncEngine, store: ModuleStore, tenant: str, local_catalog: Any) -> None:
        self.seen: list[httpx.Request] = []
        self.engine, self.store, self.tenant, self.catalog = engine, store, tenant, local_catalog
        self.bindings = PluginBindings(engine)
        loaded = discover(found=[], folders=[str(V1)])
        assert all(i.ok for i in loaded), [i.error for i in loaded]
        first = loaded[0].plugin
        assert first is not None
        self.v1: Plugin = first
        self.v2 = Plugin(read(V2), self.v1.root)
        self.host = self.host_for(self.v1)

    def host_for(self, plugin: Plugin, *, versions: bool = True) -> PluginHost:
        switches = InstallSwitches(Policy({ID: {"enabled": True}}))
        return PluginHost(self.store, self.bindings, switches, [Loaded("fields_desk", plugin, None)], versions=versions)

    def upgrade(self, *, versions: bool = True) -> None:
        self.host = self.host_for(self.v2, versions=versions)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return httpx.Response(200, json={"ok": True, "path": request.url.path})

    async def call(self, team: str, tool: str, args: dict[str, Any] | None = None) -> ToolOutcome:
        registry = ToolRegistry(self.catalog, self.store, self.host)
        found = await registry.resolve(f"fields_{tool}", tenant_id=self.tenant, team_id=team)
        assert found is not None and found.module is not None and found.operation is not None
        given = args or {}
        refused = _before_policy(found, given)
        if refused is not None:
            return ToolOutcome(False, {"error": {"code": refused[1], "status": refused[0], "message": refused[2]}})
        client = httpx.AsyncClient(transport=httpx.MockTransport(self._answer))
        http = HttpExecutor(client, AllowAll(), auth=TeamSignIn())  # type: ignore[arg-type]
        if found.executor == "plugin":
            return await PluginExecutor(self.host, http, b"k" * 32).run(
                found.module, found.operation, given, actor="t", environment="production", acting_for=None
            )
        return await http.run(found.module, found.operation, given, actor="t", environment="production")

    async def listed(self, team: str) -> set[str]:
        with acting_as(team):
            rows = await ToolRegistry(self.catalog, self.store, self.host).grantable(self.tenant, sees=lambda _m: True)
        return {r["name"] for r in rows if r["name"].startswith("fields_")}


@pytest.fixture
async def up(engine: AsyncEngine, store: ModuleStore, tenant: str, local_catalog: Any) -> Upgrade:
    u = Upgrade(engine, store, tenant, local_catalog)
    for team in ("team_ops", "team_platform"):
        await u.bindings.put(tenant, team, ID, enabled=True, connection_id="con_a", settings={}, by="t")
    # Both bindings have no version: the first ensure stamps the installed one (bindings from before the flag).
    await u.host.ensure(tenant, datetime.now(UTC))
    return u


async def ops_of(u: Upgrade) -> list[dict[str, Any]]:
    row = await u.store.get(u.tenant, "mod_plugin_fields")
    assert row is not None
    return cast(list[dict[str, Any]], row["operations"])


def path(u: Upgrade) -> str:
    return u.seen[-1].url.path if u.seen else ""


async def test_a_binding_with_no_version_is_stamped_with_the_installed_one(up: Upgrade) -> None:
    row = await up.bindings.get(up.tenant, "team_ops", ID)
    assert row is not None and row["version"] == "0.1.0" and row["digest"], row


async def test_after_an_upgrade_a_team_keeps_calling_its_version(up: Upgrade) -> None:
    before = {o["name"]: o["id"] for o in await ops_of(up)}
    up.upgrade()
    assert (await up.call("team_ops", "post_message", {"channel": "C1", "text": "hi"})).ok
    assert path(up) == "/fields/chat.postMessage", "a changed tool keeps the team's request"
    assert (await up.call("team_ops", "transfer", {"amount": 10, "to": "acct-7"})).ok, "a removed tool still answers"
    assert (await up.call("team_ops", "find", {"status": "open"})).ok
    assert path(up) == "/fields/search" and up.seen[-1].url.params.get("status") == "open", (
        "a query tool runs on the plugin executor as the team's version declared it"
    )
    sent = len(up.seen)
    pending = await up.call("team_ops", "find", {"status": "pending"})
    assert not pending.ok and pending.output["error"]["code"].lower() == "invalid_input", "the team's enum holds"
    new = await up.call("team_ops", "close_case", {"id": "case-1"})
    assert not new.ok and "takes the update" in new.output["error"]["message"], new
    assert len(up.seen) == sent
    after = {o["name"]: o for o in await ops_of(up)}
    assert all(after[n]["id"] == i for n, i in before.items()), "ids are kept by name"
    assert after["fields_transfer"]["enabled"] is False and after["fields_close_case"]["enabled"] is True


async def test_a_team_that_takes_the_update_runs_it_and_the_other_team_does_not(up: Upgrade) -> None:
    up.upgrade()
    await up.host.ensure(up.tenant, datetime.now(UTC))
    assert await up.host.take_installed(up.tenant, "team_ops", up.v2)
    assert (await up.call("team_ops", "post_message", {"channel": "C1", "text": "hi"})).ok
    assert path(up) == "/fields/chat.post"
    assert (await up.call("team_ops", "find", {"status": "pending"})).ok
    assert (await up.call("team_ops", "close_case", {"id": "case-1"})).ok
    gone = await up.call("team_ops", "transfer", {"amount": 10, "to": "acct-7"})
    assert not gone.ok and "no longer has this tool" in gone.output["error"]["message"], gone
    assert (await up.call("team_platform", "post_message", {"channel": "C1", "text": "hi"})).ok
    assert path(up) == "/fields/chat.postMessage", "the other team is still on 0.1.0"


async def test_each_teams_tool_list_matches_what_its_calls_allow(up: Upgrade) -> None:
    up.upgrade()
    old = await up.listed("team_ops")
    assert "fields_transfer" in old and "fields_close_case" not in old, old
    await up.host.ensure(up.tenant, datetime.now(UTC))
    await up.host.take_installed(up.tenant, "team_ops", up.v2)
    new = await up.listed("team_ops")
    assert "fields_close_case" in new and "fields_transfer" not in new, new


async def test_with_the_flag_off_the_row_stays_as_first_written(up: Upgrade) -> None:
    up.upgrade(versions=False)
    await up.host.ensure(up.tenant, datetime.now(UTC))
    names = {o["name"] for o in await ops_of(up)}
    assert "fields_close_case" not in names and "fields_transfer" in names, names


async def test_a_rewrite_another_process_made_first_is_left_alone(up: Upgrade, monkeypatch: pytest.MonkeyPatch) -> None:
    up.upgrade()
    real = up.store.get

    async def stale(tenant: str, module_id: str) -> Any:
        row = await real(tenant, module_id)
        return {**row, "revision": int(row["revision"]) - 1} if row else row

    monkeypatch.setattr(up.store, "get", stale)
    await up.host.ensure(up.tenant, datetime.now(UTC))
    monkeypatch.setattr(up.store, "get", real)
    names = {o["name"] for o in await ops_of(up)}
    assert "fields_close_case" not in names, "a stale write lands nothing"


# The review and the take, through the real plugin routes (c-609 T004).


@pytest.fixture
async def routes(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str
) -> AsyncIterator[tuple[httpx.AsyncClient, PluginHost, Plugin]]:
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth)
    vault = credentials()
    store = ConnectionStore(engine)
    tokens = Tokens(store, vault, httpx.AsyncClient(), AllowAll())  # type: ignore[arg-type]
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store,
        SecretResolver(SecretStore(engine), vault),
        vault,
        tokens,
        directory,
        egress=None,
        console_url=CONSOLE_URL,
    )
    loaded = discover(found=[], folders=[str(V1)])
    v1 = loaded[0].plugin
    assert v1 is not None
    switches = InstallSwitches(Policy({ID: {"enabled": True}}))
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), switches, loaded, store, versions=True)
    app.include_router(plugins_router(host, connections, directory, PluginAppKeys(engine, vault)))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        await c.post(
            "/v1/egress/hosts",
            json={"value": "api.multi.test"},
            headers=person(tenant, "Sam Adeyemi", {"team_security": "admin"}),
        )
        yield c, host, Plugin(read(V2), v1.root)


def admin(tenant: str, team: str = "team_ops") -> dict[str, str]:
    return person(tenant, "Priya Shah", {team: "admin"})


async def test_a_team_reviews_an_upgrade_and_takes_it_and_another_team_keeps_its_version(
    routes: tuple[httpx.AsyncClient, PluginHost, Plugin], tenant: str
) -> None:
    c, host, v2 = routes
    for team in ("team_ops", "team_platform"):
        on = await c.put(
            f"/v1/plugins/{ID}/team",
            json={"enabled": True, "credentials": {"token": "t-1"}},
            headers=admin(tenant, team),
        )
        assert on.status_code == 200, on.text
    current = (await c.get(f"/v1/plugins/{ID}/team/update", headers=admin(tenant))).json()["data"]
    assert current["version"] == "0.1.0" and not current["available"] and current["tools"] == [], current
    host.loaded = [Loaded("fields_desk", v2, None)]
    review = (await c.get(f"/v1/plugins/{ID}/team/update", headers=admin(tenant))).json()["data"]
    assert review["available"] and review["installed"]["version"] == "0.2.0", review
    found = {t["name"]: t for t in review["tools"]}
    assert set(found) == {"fields_find", "fields_post_message", "fields_transfer", "fields_close_case"}, found
    assert found["fields_find"]["change"] == "changed" and found["fields_find"]["inputs"]["changed"] == ["status"]
    assert found["fields_post_message"]["changed"] == ["request"] and found["fields_transfer"]["change"] == "removed"
    assert found["fields_close_case"]["change"] == "new" and found["fields_close_case"]["inputs"]["added"] == ["id"]
    listed = next(
        p for p in (await c.get("/v1/plugins", headers=admin(tenant))).json()["data"]["plugins"] if p["id"] == ID
    )
    assert listed["updateAvailable"] and listed["teamVersion"] == "0.1.0" and "fields_transfer" in listed["tools"]
    stale = await c.post(f"/v1/plugins/{ID}/team/update", json={"digest": "0" * 64}, headers=admin(tenant))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "update_changed", stale.text
    taken = await c.post(
        f"/v1/plugins/{ID}/team/update", json={"digest": review["installed"]["digest"]}, headers=admin(tenant)
    )
    assert taken.status_code == 200 and taken.json()["data"]["version"] == "0.2.0", taken.text
    assert not taken.json()["data"]["available"] and taken.json()["data"]["tools"] == []
    other = (await c.get(f"/v1/plugins/{ID}/team/update", headers=admin(tenant, "team_platform"))).json()["data"]
    assert other["version"] == "0.1.0" and other["available"], other


async def test_only_a_team_admin_reviews_or_takes_and_the_flag_off_hides_both(
    routes: tuple[httpx.AsyncClient, PluginHost, Plugin], tenant: str
) -> None:
    c, host, _ = routes
    await c.put(
        f"/v1/plugins/{ID}/team", json={"enabled": True, "credentials": {"token": "t-1"}}, headers=admin(tenant)
    )
    builder = person(tenant, "James Richardson", {"team_ops": "builder"})
    assert (await c.get(f"/v1/plugins/{ID}/team/update", headers=builder)).status_code == 403
    host.versions = False
    assert (await c.get(f"/v1/plugins/{ID}/team/update", headers=admin(tenant))).status_code == 404


async def test_a_row_first_written_by_the_new_version_still_holds_the_teams_old_tool(up: Upgrade) -> None:
    """No call reached the old version's process, so the new one writes the row first; a team on the old version
    still calls a tool only its version declares."""
    await up.store.delete(up.tenant, "mod_plugin_fields")
    up.upgrade()
    assert (await up.call("team_ops", "transfer", {"amount": 10, "to": "acct-7"})).ok
    row = {o["name"]: o for o in await ops_of(up)}
    assert row["fields_transfer"]["enabled"] is False and row["fields_close_case"]["enabled"] is True


async def test_a_restart_on_the_same_version_leaves_the_row_as_it_was(up: Upgrade) -> None:
    """Each tools-service process runs ensure: one on an unchanged package must not rewrite the row, or every boot
    bumps its revision and the processes race each other for it."""
    before = await up.store.get(up.tenant, "mod_plugin_fields")
    up.host = up.host_for(up.v1)
    await up.host.ensure(up.tenant, datetime.now(UTC))
    after = await up.store.get(up.tenant, "mod_plugin_fields")
    assert before is not None and after is not None and after["revision"] == before["revision"]
    up.upgrade()
    await up.host.ensure(up.tenant, datetime.now(UTC))
    moved = await up.store.get(up.tenant, "mod_plugin_fields")
    up.host = up.host_for(up.v2)
    await up.host.ensure(up.tenant, datetime.now(UTC))
    again = await up.store.get(up.tenant, "mod_plugin_fields")
    assert moved is not None and again is not None and again["revision"] == moved["revision"]
