"""A plugin's headers, form body and amount limit at call time (c-584), through the registry and the executors as the
gateway runs a call, by failure mode: a plugin header never reaches the system, or replaces the connection's sign-in;
a Python tool's requests go out without the plugin's headers; a team setting holding `{{NAME}}` reaches a header,
where the http executor would resolve it as one of the tenant's secrets; a form tool's body goes out as JSON; and a
transfer over its limit, or with no amount, reaches the system, including when the tenant's module row was written
before the plugin declared the limit."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, parse_qsl, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import discover
from ops_service_kit.settings import Settings
from ops_tools.auth import Authenticator, Prepared
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.connect_links import ConnectLinks
from ops_tools.executor import HttpExecutor
from ops_tools.gateway_calls import _before_policy  # pyright: ignore[reportPrivateUsage]
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost, SignInRefused, module_id_of, module_of, settle_at_sign_in
from ops_tools.registry import Resolved, ToolRegistry
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import CONSOLE_URL, build_app, credentials, response_checker
from .test_personal_sign_in import JAMES_P, SETTINGS, client, personal_connection, system
from .test_plugins import AllowAll
from .test_review_decisions import introspect, jwks, person

# pytest finds a fixture by its name in this module, so the personal sign-in rig is imported for its last test.
FIXTURES = (client, system)
TEAM = "team_ops"
ID = "test.fields"
FOLDER = Path(__file__).parent / "plugin_fields" / "fields_desk"
TOKEN = "team-token-41c7"


class TeamSignIn:
    """The connection's sign-in as the authenticator gives it: a bearer token the call must carry unchanged."""

    async def prepare(self, *_: Any, **__: Any) -> Prepared:
        return Prepared("con_a", headers={"Authorization": f"Bearer {TOKEN}"}, values=[TOKEN])


class Rig:
    def __init__(self, engine: AsyncEngine, store: ModuleStore, tenant: str, local_catalog: Any) -> None:
        self.seen: list[httpx.Request] = []
        self.tenant = tenant
        self.store = store
        self.bindings = PluginBindings(engine)
        loaded = discover(found=[], folders=[str(FOLDER)])
        assert all(item.ok for item in loaded), [item.error for item in loaded]
        self.host = PluginHost(store, self.bindings, {}, loaded)
        self.registry = ToolRegistry(local_catalog, store, self.host)
        upstream = httpx.AsyncClient(transport=httpx.MockTransport(self._answer))
        self.http = HttpExecutor(upstream, AllowAll(), auth=TeamSignIn())  # type: ignore[arg-type]
        self.plugins = PluginExecutor(self.host, self.http, b"k" * 32)

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        if request.url.path.endswith("/echo"):
            return httpx.Response(200, json={"sent": dict(request.headers)})
        return httpx.Response(200, json={"ok": True})

    async def bind(self, **settings: Any) -> None:
        await self.bindings.put(
            self.tenant, TEAM, ID, enabled=True, connection_id="con_a", settings=settings, by="test"
        )

    async def resolve(self, tool: str) -> Resolved:
        found = await self.registry.resolve(f"fields_{tool}", tenant_id=self.tenant, team_id=TEAM)
        assert found is not None and found.module is not None and found.operation is not None
        return found

    async def call(self, tool: str, args: dict[str, Any] | None = None) -> ToolOutcome:
        """The gateway's order: the registry's checks before anything leaves, then the executor the op names."""
        r = await self.resolve(tool)
        given = args or {}
        refused = _before_policy(r, given)
        if refused is not None:
            return ToolOutcome(False, {"error": {"code": refused[1], "status": refused[0], "message": refused[2]}})
        assert r.module is not None and r.operation is not None
        if r.executor == "plugin":
            return await self.plugins.run(
                r.module, r.operation, given, actor="t", environment="production", acting_for=None
            )
        return await self.http.run(r.module, r.operation, given, actor="t", environment="production")


@pytest.fixture
async def rig(engine: AsyncEngine, store: ModuleStore, tenant: str, local_catalog: Any) -> Rig:
    r = Rig(engine, store, tenant, local_catalog)
    await r.bind()
    return r


async def test_the_plugins_and_the_tools_headers_reach_the_system_beside_the_sign_in(rig: Rig) -> None:
    out = await rig.call("search", {"q": "card"})
    assert out.ok, out
    sent = rig.seen[-1].headers
    assert sent["X-Api-Version"] == "2026-10"
    assert sent["ConsistencyLevel"] == "eventual"
    assert sent["Authorization"] == f"Bearer {TOKEN}"


async def test_a_header_renders_the_teams_own_setting(rig: Rig) -> None:
    await rig.bind(api_version="2027-01")
    assert (await rig.call("search")).ok
    assert rig.seen[-1].headers["X-Api-Version"] == "2027-01"
    assert (await rig.call("post_message", {"channel": "C1", "text": "hi"})).ok
    assert "ConsistencyLevel" not in rig.seen[-1].headers, "a tool's own header goes on that tool only"


async def test_a_python_tools_requests_carry_the_plugins_headers_and_never_answer_the_sign_in(rig: Rig) -> None:
    out = await rig.call("echo")
    assert out.ok, out
    assert rig.seen[-1].headers["X-Api-Version"] == "2026-10"
    assert rig.seen[-1].headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(out.output)


@pytest.mark.parametrize("value", ["{{API_KEY}}", "2026\r\nX-Evil: 1"])
async def test_a_setting_a_header_cannot_carry_turns_the_teams_calls_off(rig: Rig, value: str) -> None:
    await rig.bind(api_version=value)
    out = await rig.call("search")
    assert not out.ok and out.output["error"]["code"] == "PLUGIN_DISABLED", out
    assert "api_version" in out.output["error"]["message"]
    assert rig.seen == []


async def test_a_form_tool_sends_its_fields_form_encoded(rig: Rig) -> None:
    out = await rig.call("post_message", {"channel": "C024BE91L", "text": "Card 1042 & more"})
    assert out.ok, out
    sent = rig.seen[-1]
    assert sent.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(sent.content.decode()) == {"channel": ["C024BE91L"], "text": ["Card 1042 & more"]}


async def test_a_form_tools_operation_is_a_form_body_as_a_custom_tools_is(rig: Rig) -> None:
    # One form path (c-616 S5): the manifest's `form` becomes the body with body_encoding form, so the tool page, the
    # executor and Request sent read a plugin's form tool as they read a builder's.
    op = (await rig.resolve("post_message")).operation
    assert op is not None and "form" not in op, op
    assert (op["body_encoding"], json.loads(op["body"])) == (
        "form",
        {"channel": "{{channel}}", "text": "{{text}}", "thread_ts": "{{thread}}"},
    )


async def test_a_transfer_within_its_limit_is_sent_and_one_over_or_without_an_amount_is_not(rig: Rig) -> None:
    assert (await rig.call("transfer", {"amount": 4999.5, "to": "acct-7"})).ok
    assert len(rig.seen) == 1
    over = await rig.call("transfer", {"amount": 5000.01, "to": "acct-7"})
    assert not over.ok and over.output["error"]["code"] == "amount_over_limit", over
    missing = await rig.call("transfer", {"to": "acct-7"})
    assert not missing.ok and missing.output["error"]["status"] == 422, missing
    assert len(rig.seen) == 1


async def test_the_limit_holds_on_a_module_row_written_before_the_plugin_declared_it(rig: Rig) -> None:
    plugin = rig.host.plugins[ID]
    old = module_of(plugin, tenant_id=rig.tenant, at=datetime.now(UTC))
    old["operations"] = [{**o, "amount_max": None, "headers": []} for o in old["operations"]]
    await rig.store.insert_if_missing(old)
    over = await rig.call("transfer", {"amount": 9000, "to": "acct-7"})
    assert not over.ok and over.output["error"]["code"] == "amount_over_limit", over
    assert rig.seen == []


# The token call and the sign-in address (c-584 T004), through the real plugin turn-on route.

ZOOM, ZOOM_SECRET = "multi-zoom", "zoom-secret-6d0e"


class TokenDesk:
    """A system whose login host takes the client only as basic auth, as Zoom's does, and records each token request
    as it arrived: whether the client came in a Basic header, and the form without its secret."""

    def __init__(self) -> None:
        self.token_requests: list[dict[str, Any]] = []
        self.seen: list[httpx.Request] = []

    def answer(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/token"):
            form = dict(parse_qsl(request.content.decode()))
            basic = request.headers.get("authorization", "")
            self.token_requests.append(
                {"basic": basic.startswith("Basic "), **{k: v for k, v in form.items() if k != "client_secret"}}
            )
            given = base64.b64decode(basic[6:]).decode() if basic.startswith("Basic ") else ""
            if "client_secret" in form or given != f"{ZOOM}:{ZOOM_SECRET}":
                return httpx.Response(401, json={"error": "invalid_client"})
            return httpx.Response(200, json={"access_token": "zoom-at-1", "token_type": "Bearer", "expires_in": 3600})
        self.seen.append(request)
        ok = request.headers.get("authorization") == "Bearer zoom-at-1"
        return httpx.Response(200 if ok else 401, json={"record": {"id": "rec-1042"}})


@pytest.fixture
async def desk_rig(engine: AsyncEngine, seed: dict[str, Any], tenant: str) -> AsyncIterator[tuple[Any, TokenDesk]]:
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    desk = TokenDesk()
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(desk.answer))
    vault = credentials()
    store = ConnectionStore(engine)
    tokens = Tokens(store, vault, upstream, AllowAll())  # type: ignore[arg-type]
    loaded = discover(found=[], folders=[str(p) for p in sorted(FOLDER.parent.glob("fields_*"))])
    assert all(item.ok for item in loaded), [item.error for item in loaded]
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), {}, loaded, store)
    app = build_app(engine, seed, tenant, auth=auth, upstream=upstream, plugins=host)
    authenticator = Authenticator(
        store, SecretResolver(SecretStore(engine), vault), tokens, ConnectLinks(store, CONSOLE_URL)
    )
    http = HttpExecutor(upstream, AllowAll(), auth=authenticator)  # type: ignore[arg-type]
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://tools",
        event_hooks={"response": [response_checker(app)]},
    ) as c:
        for h in ("api.multi.test", "login.multi.test"):
            await c.post("/v1/egress/hosts", json={"value": h}, headers=security)
        yield (c, host, store, http), desk


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def turn_on(c: httpx.AsyncClient, tenant: str, plugin: str, **body: Any) -> httpx.Response:
    return await c.put(f"/v1/apps/plugin:{plugin}/team", json={"enabled": True, **body}, headers=admin(tenant))


async def test_a_plugins_token_call_sends_the_client_as_basic_auth_and_never_in_the_form(
    desk_rig: tuple[Any, TokenDesk], tenant: str
) -> None:
    (c, host, _, http), desk = desk_rig
    on = await turn_on(c, tenant, "test.fields-zoom", clientId=ZOOM, clientSecret=ZOOM_SECRET)
    assert on.status_code == 200, on.text
    await host.ensure(tenant, datetime.now(UTC))
    module = await host.store.get(tenant, module_id_of(host.plugins["test.fields-zoom"].manifest))
    assert module is not None
    seen = await host.for_call(tenant, TEAM, module, "production")
    op = next(o for o in seen["operations"] if o["name"] == "fields_zoom_get_record")
    out = await http.run(seen, op, {"id": "rec-1042"}, actor="t", environment="production")
    assert out.ok, out.output
    assert desk.token_requests and all(r["basic"] and "client_id" not in r for r in desk.token_requests), (
        desk.token_requests
    )


async def test_how_the_client_is_sent_and_the_sign_in_parameters_are_the_plugins_not_typed(
    desk_rig: tuple[Any, TokenDesk], tenant: str
) -> None:
    (c, _, store, _), _ = desk_rig
    typed = await turn_on(
        c, tenant, "test.fields-zoom", clientId=ZOOM, clientSecret=ZOOM_SECRET, credentials={"clientAuth": "body"}
    )
    assert typed.status_code == 400 and "clientAuth" in typed.text, typed.text
    on = await turn_on(c, tenant, "test.fields-sites", clientId="multi-app", clientSecret="app-secret")
    assert on.status_code == 200, on.text
    conn = await store.get(tenant, str(on.json()["data"]["connectionId"]))
    assert conn is not None
    keys = conn["settings"]
    assert parse_qs(keys["authorizeParams"]) == {"audience": ["api.multi.test"], "prompt": ["consent"]}, keys


async def test_a_connections_sign_in_parameters_reach_the_sign_in_address_and_never_replace_the_platforms(
    client: httpx.AsyncClient,
    tenant: str,
) -> None:
    conn = await personal_connection(
        client, tenant,
        {**SETTINGS, "authorizeParams": "audience=api.bank.test&prompt=consent&state=evil&redirect_uri=https://evil.test&Client_Id=x"},
    )  # fmt: skip
    started = await client.post(f"/v1/apps/{conn}/accounts/{conn}/sign-in", json={}, headers=person(tenant, *JAMES_P))
    assert started.status_code == 200, started.text
    query = parse_qs(urlsplit(str(started.json()["data"]["authorizeUrl"])).query)
    assert query["audience"] == ["api.bank.test"] and query["prompt"] == ["consent"], query
    assert query["state"] != ["evil"] and query["redirect_uri"] != ["https://evil.test"], query
    assert query["client_id"] == ["ops-console"] and "Client_Id" not in query, query


# The lookup after sign-in (c-584 T005), on a plugin's real connection.


def test_the_team_sets_or_replaces_a_value_filled_at_sign_in_and_a_person_may_not_change_it() -> None:
    """The one rule for whose sign-in sets the instance or site (settle_at_sign_in), kept apart so it can change."""
    held = {"site_id": "site-7f3a"}
    assert settle_at_sign_in({}, {"site_id": "site-7f3a"}, own=True) == {"site_id": "site-7f3a"}
    assert settle_at_sign_in(held, {"site_id": "site-7f3a"}, own=True) == {"site_id": "site-7f3a"}
    assert settle_at_sign_in(held, {"site_id": "site-other"}, own=False) == {"site_id": "site-other"}
    with pytest.raises(SignInRefused) as refused:
        settle_at_sign_in(held, {"site_id": "site-other"}, own=True)
    assert refused.value.code == "another_site" and "signed in to another site" in str(refused.value)


def sites(answer: httpx.Response) -> tuple[httpx.AsyncClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer

    return httpx.AsyncClient(transport=httpx.MockTransport(handle)), seen


async def signed_in_sites(desk_rig: tuple[Any, TokenDesk], tenant: str) -> tuple[PluginHost, str]:
    (c, host, _, _), _ = desk_rig
    on = await turn_on(c, tenant, "test.fields-sites", clientId="multi-app", clientSecret="app-secret")
    assert on.status_code == 200, on.text
    host.policy = AllowAll()  # type: ignore[assignment]
    await host.ensure(tenant, datetime.now(UTC))
    return host, str(on.json()["data"]["connectionId"])


async def endpoint_of(host: PluginHost, tenant: str) -> str:
    module = await host.store.get(tenant, module_id_of(host.plugins["test.fields-sites"].manifest))
    assert module is not None
    return str((await host.for_call(tenant, TEAM, module, "production")).get("endpoint"))


async def test_the_lookup_fills_the_site_with_the_new_token_and_calls_reach_it(
    desk_rig: tuple[Any, TokenDesk], tenant: str
) -> None:
    host, conn = await signed_in_sites(desk_rig, tenant)
    host.http, seen = sites(httpx.Response(200, json=[{"id": "site-7f3a", "name": "Harbor desk"}]))
    await host.on_token(tenant, conn, {"access_token": "at-team"})
    assert seen and str(seen[0].url) == "https://api.multi.test/sites/accessible"
    assert seen[0].headers["authorization"] == "Bearer at-team"
    assert await endpoint_of(host, tenant) == "https://api.multi.test/sites/site-7f3a"


async def test_a_persons_sign_in_on_another_site_is_refused_and_the_team_keeps_its_own(
    desk_rig: tuple[Any, TokenDesk], tenant: str
) -> None:
    host, conn = await signed_in_sites(desk_rig, tenant)
    host.http, _ = sites(httpx.Response(200, json=[{"id": "site-7f3a"}]))
    await host.on_token(tenant, conn, {"access_token": "at-team"})
    host.http, _ = sites(httpx.Response(200, json=[{"id": "site-other"}]))
    with pytest.raises(SignInRefused) as refused:
        await host.on_token(tenant, conn, {"access_token": "at-james"}, own=True)
    assert refused.value.code == "another_site"
    assert await endpoint_of(host, tenant) == "https://api.multi.test/sites/site-7f3a"
    await host.on_token(tenant, conn, {"access_token": "at-team-2"})
    assert await endpoint_of(host, tenant) == "https://api.multi.test/sites/site-other"


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (httpx.Response(302, headers={"location": "https://elsewhere.test/sites"}), "lookup_failed"),
        (httpx.Response(401, json={"error": "invalid_token"}), "lookup_failed"),
        (httpx.Response(200, json=[]), "lookup_failed"),
        (httpx.Response(200, json=[{"id": "../admin?x=1"}]), "lookup_failed"),
        (httpx.Response(200, json=[{"id": "https://evil.example"}]), "token_host"),
    ],
)
async def test_a_lookup_that_fails_redirects_or_names_another_host_fails_the_sign_in_and_saves_nothing(
    desk_rig: tuple[Any, TokenDesk], tenant: str, answer: httpx.Response, code: str
) -> None:
    host, conn = await signed_in_sites(desk_rig, tenant)
    host.http, _ = sites(answer)
    with pytest.raises(SignInRefused) as refused:
        await host.on_token(tenant, conn, {"access_token": "at-team"})
    assert refused.value.code == code, refused.value
    assert (await host.own_settings(tenant, conn)).get("site_id") is None
