"""Hosts the tenant has not listed, by failure mode: a plugin's own host is refused for its own sign-in; a plugin's host
opens a door for any other call, through the check or through a pooled connection; `any_public` reaches a private,
metadata or literal address; `block` and `builders` behave as `ask_security`; an unreadable policy opens public hosts;
and a policy value outside its four choices is stored."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.policies import check_value
from ops_identity import Auth, Identity, ServiceAuth, ServiceUnreachable, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.egress import EgressBackend, EgressDenied, EgressPolicy, EgressTransport, NewHosts, for_tenant
from ops_tools.modules.seed import load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker
from .test_egress import Dialled, RecordingNetwork, ScriptedResolver, _dial  # pyright: ignore[reportPrivateUsage]
from .test_review_decisions import REVIEWS, introspect, jwks, person

PLUGIN_HOST = "login.vendor.example"


class Mode:
    def __init__(self, mode: str) -> None:
        self.value = mode

    async def mode(self, tenant_id: str) -> str:
        return self.value


def _policy(engine: AsyncEngine, answers: dict[str, list[list[str]]], mode: str | None = None) -> EgressPolicy:
    return EgressPolicy(EgressStore(engine), ScriptedResolver(answers), Mode(mode) if mode else None)  # pyright: ignore[reportArgumentType]


async def test_a_plugins_own_host_passes_for_its_requests_only(engine: AsyncEngine, tenant: str) -> None:
    policy = _policy(engine, {PLUGIN_HOST: [["93.184.216.34"]]})
    url = f"https://{PLUGIN_HOST}/services/oauth2/token"
    assert await policy.check_url(tenant, url, [PLUGIN_HOST]) == PLUGIN_HOST
    with pytest.raises(EgressDenied):
        await policy.check_url(tenant, url)
    resolver = ScriptedResolver({PLUGIN_HOST: [["93.184.216.34"]]})
    own = EgressBackend(policy, tenant, RecordingNetwork(resolver), frozenset({PLUGIN_HOST}))
    assert await _dial(own, PLUGIN_HOST) == "93.184.216.34"
    with pytest.raises(EgressDenied):
        await _dial(EgressBackend(policy, tenant, RecordingNetwork(resolver)), PLUGIN_HOST)


async def test_a_connection_opened_for_a_plugins_host_serves_no_other_request(engine: AsyncEngine, tenant: str) -> None:
    resolver = ScriptedResolver({PLUGIN_HOST: [["93.184.216.34"]]})
    policy = EgressPolicy(EgressStore(engine), resolver)
    transport = EgressTransport(policy, httpx.create_ssl_context(), network=RecordingNetwork(resolver))
    url = f"https://{PLUGIN_HOST}/token"
    with pytest.raises(Dialled):
        await transport.handle_async_request(
            httpx.Request("POST", url, extensions=for_tenant(tenant, hosts=[PLUGIN_HOST]))
        )
    with pytest.raises(EgressDenied):
        await transport.handle_async_request(httpx.Request("POST", url, extensions=for_tenant(tenant)))
    assert transport.pools[tenant] is not next(iter(transport.plugin_pools.values()))


async def test_a_plugins_host_still_never_reaches_a_private_or_metadata_address(
    engine: AsyncEngine, tenant: str
) -> None:
    for address in ("10.0.0.5", "169.254.169.254", "127.0.0.1", "fd00::1"):
        resolver = ScriptedResolver({PLUGIN_HOST: [[address]]})
        policy = EgressPolicy(EgressStore(engine), resolver)
        backend = EgressBackend(policy, tenant, RecordingNetwork(resolver), frozenset({PLUGIN_HOST}))
        with pytest.raises(EgressDenied):
            await _dial(backend, PLUGIN_HOST)
    assert "10.0.0.5" not in for_tenant(tenant, hosts=["10.0.0.5"]).get("ops_plugin_hosts", frozenset())


async def test_any_public_reaches_public_names_and_nothing_private(engine: AsyncEngine, tenant: str) -> None:
    answers = {"api.anywhere.example": [["93.184.216.34"]], "inside.anywhere.example": [["10.1.2.3"]]}
    policy = _policy(engine, answers, "any_public")
    assert await policy.check_url(tenant, "https://api.anywhere.example/v1") == "api.anywhere.example"
    for refused in ("http://api.anywhere.example/v1", "https://api.anywhere.example:8443/", "https://93.184.216.34/"):
        with pytest.raises(EgressDenied):
            await policy.check_url(tenant, refused)
    resolver = ScriptedResolver(answers)
    backend = EgressBackend(policy, tenant, RecordingNetwork(resolver))
    assert await _dial(backend, "api.anywhere.example") == "93.184.216.34"
    with pytest.raises(EgressDenied):
        await _dial(backend, "inside.anywhere.example")


async def test_without_any_public_an_unlisted_name_is_refused(engine: AsyncEngine, tenant: str) -> None:
    for mode in ("ask_security", "builders", "block", None):
        policy = _policy(engine, {"api.anywhere.example": [["93.184.216.34"]]}, mode)
        with pytest.raises(EgressDenied):
            await policy.check_url(tenant, "https://api.anywhere.example/v1")


async def test_a_policy_that_cannot_be_read_asks_security() -> None:
    class Down:
        async def get(self, path: str, *, tenant: str) -> Any:
            raise ServiceUnreachable("platform")

    class Odd:
        async def get(self, path: str, *, tenant: str) -> Any:
            return {"value": "open"}

    assert await NewHosts(Down()).mode("t") == "ask_security"
    assert await NewHosts(Odd()).mode("t") == "ask_security"


def test_the_policy_takes_only_its_four_choices() -> None:
    for mode in ("ask_security", "builders", "any_public", "block"):
        assert check_value("egressNewHosts", mode) == mode
    for bad in ("open", True, None, ["any_public"]):
        with pytest.raises(ValueError):
            check_value("egressNewHosts", bad)


OP = {
    "name": "get_statement",
    "description": "Monthly statement",
    "access": "read",
    "method": "GET",
    "url": "https://new-statements.example.com/v1/accounts/{accountId}/statement",
}


@pytest.fixture
def builder_app(engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]):
    async def make(mode: str) -> AsyncIterator[httpx.AsyncClient]:
        await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
        settings = Settings()
        auth = Auth(
            Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
            ServiceAuth(
                audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes
            ),
        )
        app = build_app(engine, seed, tenant, auth=auth, reviews=REVIEWS, new_hosts=Mode(mode))
        hooks = {"response": [response_checker(app)]}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
        ) as c:
            yield c

    return make


async def _add_operation(c: httpx.AsyncClient, tenant: str, name: str) -> httpx.Response:
    james = person(tenant, "James Richardson", {"team_platform": "builder"})
    made = await c.post(
        "/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}, headers=james
    )
    return await c.post(f"/v1/tool-modules/{made.json()['data']['id']}/operations", json=OP, headers=james)


async def test_builders_list_a_new_host_in_their_own_name(builder_app: Any, engine: AsyncEngine, tenant: str) -> None:
    async for c in builder_app("builders"):
        added = await _add_operation(c, tenant, "nh-builders")
        assert added.status_code == 200, added.text
        trail = [(a["value"], a["actor"]) for a in await EgressStore(engine).audit(tenant)]
        assert ("new-statements.example.com", "James Richardson") in trail


async def test_block_refuses_a_new_host_and_asks_nobody(builder_app: Any, engine: AsyncEngine, tenant: str) -> None:
    REVIEWS.hosts.clear()
    async for c in builder_app("block"):
        refused = await _add_operation(c, tenant, "nh-block")
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "egress_denied", refused.text
        assert not REVIEWS.hosts, "block opens no task for Security"
        assert not await EgressStore(engine).host_allowed(tenant, "new-statements.example.com")


async def test_ask_security_holds_a_new_host(builder_app: Any, tenant: str) -> None:
    REVIEWS.hosts.clear()
    async for c in builder_app("ask_security"):
        held = await _add_operation(c, tenant, "nh-ask")
        assert held.status_code == 202 and held.json()["data"]["heldFor"] == "security", held.text
