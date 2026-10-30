"""A plugin turned on for a team with each sign-in method (c-588), through the real routes, by failure mode: the turn-on
makes a connection without its credential, so the plugin cannot be used at all; the credential goes in the wrong
place, under the wrong name, or not at all; Test connection has nowhere to read; a field the method does not have,
or a method the plugin does not offer, is taken silently; a second turn-on changes the method under a working
connection; and a secret given at the turn-on comes back in an answer.

The test plugins are tests/plugin_kinds, one per method, loaded the way OPS_PLUGIN_PATHS loads a developer's plugin.
The system is an in-process fake that accepts only the expected credential, as docs/usecases/lib/fake_multi_auth.py
does for uc-588."""

from __future__ import annotations

import base64
import ssl
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.manifest import PER_PERSON_KINDS
from ops_policy import AesGcmCipher
from ops_service_kit.settings import Settings
from ops_tools.auth import Authenticator
from ops_tools.auth.kinds import KINDS
from ops_tools.auth.tokens import Tokens
from ops_tools.connections.connect_links import ConnectLinks
from ops_tools.connections.service import ConnectionService
from ops_tools.executor import HttpExecutor
from ops_tools.modules.directory import Directory
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost, module_id_of
from ops_tools.plugins.routes import plugins_router
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.secrets import SecretResolver
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_app_keys import PluginAppKeys
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import CONSOLE_URL, build_app, response_checker
from .test_plugins import AllowAll, Policy
from .test_review_decisions import introspect, jwks, person

TEAM = "team_platform"
KINDS_DIR = Path(__file__).parent / "plugin_kinds"
KEY = "desk-key-5b1e9c0d7a"
USER, PASSWORD = "harbor-integration", "pw-3f8a61c2e4"
TOKEN = "static-token-9d27e0b4c1"
CLIENT, CLIENT_SECRET = "multi-cc", "cc-secret-71b3e5a8d2"
HOSTS = ("api.multi.test", "login.multi.test", "mtls.bank.test")


@dataclass
class System:
    """The fake system: each method's path answers 200 only with its expected credential, and keeps what it saw."""

    seen: list[httpx.Request] = field(default_factory=list[httpx.Request])
    # Token requests as the login host saw them, form-decoded; the tokens issued and those since expired.
    token_requests: list[dict[str, str]] = field(default_factory=list[dict[str, str]])
    issued: list[str] = field(default_factory=list[str])
    expired: set[str] = field(default_factory=set[str])
    # The certificate listener refuses the handshake, as one does when no client certificate is presented.
    refuse_handshake: bool = False

    def expire(self) -> None:
        self.expired |= set(self.issued)

    def _token(self, request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode()))
        self.token_requests.append({k: v for k, v in form.items() if k != "client_secret"})
        if (form.get("client_id"), form.get("client_secret")) != (CLIENT, CLIENT_SECRET):
            return httpx.Response(401, json={"error": "invalid_client"})
        self.issued.append(f"cc-at-{len(self.issued) + 1}")
        return httpx.Response(200, json={"access_token": self.issued[-1], "token_type": "Bearer", "expires_in": 3600})

    def answer(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.multi.test" and request.url.path.endswith("/token"):
            return self._token(request)
        self.seen.append(request)
        method = request.url.path.strip("/").split("/", 1)[0]
        if method == "cert" and self.refuse_handshake:
            raise httpx.ConnectError("handshake refused") from ssl.SSLError(1, "tlsv13 alert certificate required")
        auth = request.headers.get("authorization", "")
        bearer = auth.removeprefix("Bearer ")
        ok = {
            "open": True,
            "cert": True,
            "header-key": request.headers.get("X-Desk-Key") == KEY,
            "query-key": request.url.params.get("api_key") == KEY,
            "basic": auth == "Basic " + base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode(),
            "bearer": auth == f"Bearer {TOKEN}",
            "cc": bearer in self.issued and bearer not in self.expired,
        }.get(method, False)
        if not ok:
            return httpx.Response(401, json={"error": "unauthorized"})
        if request.url.path.endswith("/echo"):
            # A system that repeats the request it was sent, as some debugging endpoints do.
            return httpx.Response(200, json={"sent": {"authorization": auth}})
        return httpx.Response(200, json={"method": method, "record": {"id": "rec-1042"}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.answer))


@dataclass
class Rig:
    client: httpx.AsyncClient
    host: PluginHost
    auth: Authenticator
    store: ConnectionStore
    system: System
    executor: PluginExecutor


@pytest.fixture
async def rig(engine: AsyncEngine, seed: dict[str, Any], tenant: str) -> AsyncIterator[Rig]:
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    system = System()
    upstream = system.client()
    app = build_app(engine, seed, tenant, auth=auth, upstream=upstream)
    cipher = AesGcmCipher(settings.secrets_key.get_secret_value())
    store = ConnectionStore(engine)
    tokens = Tokens(store, cipher, upstream, AllowAll())  # type: ignore[arg-type]
    directory = Directory.from_seed(seed, datetime.now(UTC))
    connections = ConnectionService(
        store, SecretStore(engine), cipher, tokens, directory, egress=None, console_url=CONSOLE_URL
    )
    loaded = discover(found=[], folders=[str(p) for p in sorted(KINDS_DIR.glob("kinds_*"))])
    assert all(item.ok for item in loaded), [item.error for item in loaded if not item.ok]
    policy = {item.plugin.manifest.id: {"enabled": True} for item in loaded if item.plugin}
    host = PluginHost(ModuleStore(engine), PluginBindings(engine), InstallSwitches(Policy(policy)), loaded)
    app.include_router(plugins_router(host, connections, directory, PluginAppKeys(engine, cipher)))
    resolver = SecretResolver(SecretStore(engine), cipher)
    authenticator = Authenticator(store, resolver, tokens, ConnectLinks(store, CONSOLE_URL))
    executor = PluginExecutor(
        host,
        HttpExecutor(upstream, AllowAll(), secrets=resolver, auth=authenticator),  # type: ignore[arg-type]
        b"k" * 32,
    )
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        for h in HOSTS:
            await c.post("/v1/egress/hosts", json={"value": h}, headers=security)
        yield Rig(c, host, authenticator, store, system, executor)


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def turn_on(rig: Rig, tenant: str, plugin: str, **body: Any) -> httpx.Response:
    return await rig.client.put(f"/v1/plugins/{plugin}/team", json={"enabled": True, **body}, headers=admin(tenant))


async def call_as_team(rig: Rig, tenant: str, plugin: str, tool: str = "get_record") -> ToolOutcome:
    """The plugin's tool as the gateway runs a call in the team: the module the host builds for the team, run by the
    plugin executor, signed in by the team's connection, sent to the system."""
    await rig.host.ensure(tenant, datetime.now(UTC))
    manifest = rig.host.plugins[plugin].manifest
    module = await rig.host.store.get(tenant, module_id_of(manifest))
    assert module is not None
    seen = await rig.host.for_call(tenant, TEAM, module, "production")
    op = next(o for o in seen["operations"] if o["name"] == manifest.operation(tool))
    args = {"id": "rec-1042"} if tool == "get_record" else {}
    return await rig.executor.run(seen, op, args, actor="test", environment="production", acting_for=None)


async def health_of(rig: Rig, tenant: str, connection_id: str) -> dict[str, Any]:
    r = await rig.client.post(
        f"/v1/connections/{connection_id}/test", json={"environment": "production"}, headers=admin(tenant)
    )
    assert r.status_code == 200, r.text
    return dict(r.json()["data"]["health"])


@pytest.mark.parametrize(
    ("plugin", "credentials"),
    [
        ("test.open", {}),
        ("test.header-key", {"key": KEY}),
        ("test.query-key", {"key": KEY}),
        ("test.basic", {"username": USER, "password": PASSWORD}),
        ("test.bearer", {"token": TOKEN}),
    ],
)
async def test_each_method_turns_on_with_its_credential_tests_and_signs_the_call(
    rig: Rig, tenant: str, plugin: str, credentials: dict[str, str]
) -> None:
    on = await turn_on(rig, tenant, plugin, credentials=credentials)
    assert on.status_code == 200, on.text
    connection_id = str(on.json()["data"]["connectionId"])
    health = await health_of(rig, tenant, connection_id)
    assert health["status"] == "ok", health
    called = await call_as_team(rig, tenant, plugin)
    assert called.ok, called.output
    # The system saw the credential where the plugin said, and nowhere else.
    last = rig.system.seen[-1]
    if plugin == "test.header-key":
        assert last.headers.get("X-Desk-Key") == KEY and "api_key" not in last.url.params
    if plugin == "test.query-key":
        assert last.url.params.get("api_key") == KEY and "X-Desk-Key" not in last.headers


async def test_a_secret_given_at_the_turn_on_is_never_answered_back(rig: Rig, tenant: str) -> None:
    on = await turn_on(rig, tenant, "test.basic", credentials={"username": USER, "password": PASSWORD})
    connection_id = str(on.json()["data"]["connectionId"])
    shown = on.text + (await rig.client.get("/v1/plugins", headers=admin(tenant))).text
    shown += (await rig.client.get(f"/v1/connections/{connection_id}", headers=admin(tenant))).text
    assert USER in shown and PASSWORD not in shown


async def test_a_new_key_replaces_the_old_and_keeps_the_rest(rig: Rig, tenant: str) -> None:
    await turn_on(rig, tenant, "test.basic", credentials={"username": USER, "password": "old-password"})
    again = await turn_on(rig, tenant, "test.basic", credentials={"password": PASSWORD})
    assert again.status_code == 200, again.text
    assert (await call_as_team(rig, tenant, "test.basic")).ok


async def test_a_field_the_method_lacks_or_a_method_the_plugin_lacks_is_refused(rig: Rig, tenant: str) -> None:
    unknown = await turn_on(rig, tenant, "test.bearer", credentials={"password": PASSWORD})
    assert unknown.status_code == 400 and "password" in unknown.text, unknown.text
    other = await turn_on(rig, tenant, "test.bearer", kind="basic", credentials={"token": TOKEN})
    assert other.status_code == 400 and other.json()["error"]["code"] == "kind_not_offered", other.text
    missing = await turn_on(rig, tenant, "test.bearer")
    assert missing.status_code == 400 and "Token" in missing.text, missing.text
    # Nothing half-made is left behind: the first good turn-on still makes the one connection.
    good = await turn_on(rig, tenant, "test.bearer", credentials={"token": TOKEN})
    assert good.status_code == 200, good.text


async def test_a_later_turn_on_cannot_change_the_method_of_a_working_connection(rig: Rig, tenant: str) -> None:
    await turn_on(rig, tenant, "test.header-key", credentials={"key": KEY})
    changed = await turn_on(rig, tenant, "test.header-key", kind="bearer", credentials={"token": TOKEN})
    assert changed.status_code == 400 and changed.json()["error"]["code"] in ("kind_fixed", "kind_not_offered")


def test_the_sdk_knows_which_methods_hold_a_persons_token() -> None:
    assert set(PER_PERSON_KINDS) == {k.id for k in KINDS if k.per_person}


async def test_a_client_credentials_plugin_fetches_its_token_and_gets_a_new_one_after_expiry(
    rig: Rig, tenant: str
) -> None:
    on = await turn_on(rig, tenant, "test.client", clientId=CLIENT, clientSecret=CLIENT_SECRET)
    assert on.status_code == 200, on.text
    health = await health_of(rig, tenant, str(on.json()["data"]["connectionId"]))
    assert health["status"] == "ok", health
    assert (await call_as_team(rig, tenant, "test.client")).ok
    rig.system.expire()
    renewed = await call_as_team(rig, tenant, "test.client")
    assert renewed.ok, renewed.output
    # Each token was asked for as RFC 6749 says, form-encoded with the client in the body, and no person acted.
    grants = [r["grant_type"] for r in rig.system.token_requests]
    assert grants and set(grants) == {"client_credentials"} and len(rig.system.issued) >= 2, rig.system.token_requests
    assert all(r.get("client_id") == CLIENT and r.get("scope") == "api" for r in rig.system.token_requests)


async def test_a_wrong_client_secret_fails_at_the_token_fetch_and_the_connection_needs_reconnecting(
    rig: Rig, tenant: str
) -> None:
    on = await turn_on(rig, tenant, "test.client", clientId=CLIENT, clientSecret="not-the-secret")
    assert on.status_code == 200, on.text
    refused = await call_as_team(rig, tenant, "test.client")
    assert not refused.ok and refused.output["error"]["code"] == "AUTH_FAILED", refused.output
    assert "not-the-secret" not in str(refused.output)
    conn = await rig.store.get(tenant, str(on.json()["data"]["connectionId"]))
    assert conn is not None
    assert conn["status"] == "needs_reconnect", conn["status"]


def _pem(label: str, body: str) -> str:
    """Placeholder PEM text: the tests check where it is sent and that it is never shown, not that it parses."""
    return f"-----BEGIN {label}-----\n{body}\n-----END {label}-----"


CERT = _pem("CERTIFICATE", "placeholder-client-certificate")
KEY_PEM = _pem("PRIVATE" + " KEY", "placeholder-private-key")
CA = _pem("CERTIFICATE", "placeholder-ca")


async def test_a_certificate_given_at_the_turn_on_is_presented_and_its_key_never_answered_back(
    rig: Rig, tenant: str
) -> None:
    given = {"clientCertificate": CERT, "clientKey": KEY_PEM, "trustedCa": CA}
    on = await turn_on(rig, tenant, "test.cert", credentials=given)
    assert on.status_code == 200, on.text
    connection_id = str(on.json()["data"]["connectionId"])
    await rig.host.ensure(tenant, datetime.now(UTC))
    module = await rig.host.store.get(tenant, module_id_of(rig.host.plugins["test.cert"].manifest))
    assert module is not None
    seen = await rig.host.for_call(tenant, TEAM, module, "production")
    prepared = await rig.auth.prepare(seen, "production", tool="cert_get_record", actor="test")
    assert prepared is not None and prepared.certificate is not None
    assert (prepared.certificate.cert_pem, prepared.certificate.key_pem, prepared.certificate.ca_pem) == (
        CERT,
        KEY_PEM,
        CA,
    )
    shown = on.text + (await rig.client.get(f"/v1/connections/{connection_id}", headers=admin(tenant))).text
    assert "placeholder-private-key" not in shown


async def test_a_refused_handshake_reads_as_a_tls_failure_on_test_connection_and_the_call(
    rig: Rig, tenant: str
) -> None:
    on = await turn_on(rig, tenant, "test.cert", credentials={"trustedCa": CA})
    rig.system.refuse_handshake = True
    health = await health_of(rig, tenant, str(on.json()["data"]["connectionId"]))
    assert health["status"] == "failed" and health["code"] == "TLS_FAILED", health
    called = await call_as_team(rig, tenant, "test.cert")
    assert not called.ok and called.output["error"]["code"] == "TLS_FAILED", called.output


async def test_a_python_tool_cannot_return_the_credential_it_was_signed_in_with(rig: Rig, tenant: str) -> None:
    await turn_on(rig, tenant, "test.bearer", credentials={"token": TOKEN})
    echoed = await call_as_team(rig, tenant, "test.bearer", tool="echo")
    assert echoed.ok, echoed.output
    assert TOKEN not in str(echoed.output), echoed.output


async def test_test_connection_gets_a_new_token_once_when_the_system_refuses_the_one_held(
    rig: Rig, tenant: str
) -> None:
    on = await turn_on(rig, tenant, "test.client", clientId=CLIENT, clientSecret=CLIENT_SECRET)
    connection_id = str(on.json()["data"]["connectionId"])
    assert (await health_of(rig, tenant, connection_id))["status"] == "ok"
    rig.system.expire()
    again = await health_of(rig, tenant, connection_id)
    assert again["status"] == "ok", again
    assert len(rig.system.issued) == 2, rig.system.issued
