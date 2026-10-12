"""ops_identity by failure mode (spec section 4 and I1, I9, I13, I14): a token from another key, an unknown kid that
never refetches or refetches forever, a token for another service, a team outside the token, a key that keeps
working after revocation or is introspected on every request, a read key that writes, a service token accepted on
a public route or a user token on an internal one, and dev mode honoured outside dev."""

# No `from __future__ import annotations`: the test routes name local objects in Depends(), which FastAPI would
# otherwise resolve as strings against module globals.

from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI

from ops_identity import Identity, Principal, ServiceAuth, mint_service_token
from ops_policy import Ed25519Signer, mint
from ops_service_kit.http import install_error_handlers

ISSUER = Ed25519Signer.generate("platform-1")
SERVICES = Ed25519Signer.generate("services-1")


def person(**claims: Any) -> str:
    body = {
        "sub": "usr_1",
        "email": "a@bank.test",
        "name": "Ana",
        "tenant_id": "ten_a",
        "team_ids": ["team_a"],
        "roles": {"team_a": "builder"},
        "kind": "person",
        "auth_method": "session",
        "aud": ["platform", "agents"],
        **claims,
    }
    return mint(body, ISSUER, ttl_s=900)


class Platform:
    """Stands in for platform-service's JWKS and introspection, counting calls."""

    def __init__(self) -> None:
        self.keys = [ISSUER.public_jwk()]
        self.jwks_calls = 0
        self.introspect_calls = 0
        self.api_keys: dict[str, dict[str, Any]] = {}

    async def jwks(self) -> dict[str, Any]:
        self.jwks_calls += 1
        return {"keys": list(self.keys)}

    async def introspect(self, api_key: str) -> dict[str, Any] | None:
        self.introspect_calls += 1
        return self.api_keys.get(api_key)


def key_principal(scopes: list[str]) -> dict[str, Any]:
    return {
        "kind": "api_key",
        "sub": "usr_1",
        "email": "a@bank.test",
        "name": "Ana",
        "tenantId": "ten_a",
        "teamId": "team_a",
        "teamIds": ["team_a"],
        "roles": {},
        "scopes": scopes,
        "authMethod": "api_key",
    }


def app_for(identity: Identity, services: ServiceAuth | None = None) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/v1/things")
    async def read(p: Annotated[Principal, Depends(identity.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    @app.post("/v1/things")
    async def write(p: Annotated[Principal, Depends(identity.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    if services is not None:

        @app.post("/internal/fire")
        async def fire(p: Annotated[Principal, Depends(services.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return p.model_dump()

    return app


def identity(platform: Platform, **kw: Any) -> Identity:
    return Identity(audience="agents", jwks=platform.jwks, introspect=platform.introspect, **kw)


async def call(app: FastAPI, method: str, path: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc") as c:
        return await c.request(method, path, headers=headers)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_a_platform_token_resolves_tenant_team_and_roles() -> None:
    app = app_for(identity(Platform()))
    r = await call(app, "GET", "/v1/things", **bearer(person()))
    assert r.status_code == 200, r.text
    p = r.json()
    assert (p["tenant_id"], p["team_id"], p["roles"], p["kind"]) == ("ten_a", "team_a", {"team_a": "builder"}, "person")


async def test_no_credentials_and_a_token_from_another_key_are_401() -> None:
    app = app_for(identity(Platform()))
    assert (await call(app, "GET", "/v1/things")).status_code == 401
    forged = mint(
        {"sub": "usr_1", "tenant_id": "ten_a", "aud": "agents"}, Ed25519Signer.generate("platform-1"), ttl_s=60
    )
    assert (await call(app, "GET", "/v1/things", **bearer(forged))).status_code == 401


async def test_an_expired_token_is_401() -> None:
    app = app_for(identity(Platform()))
    old = mint({"sub": "usr_1", "tenant_id": "ten_a", "aud": "agents"}, ISSUER, ttl_s=60, now=1_000_000)
    assert (await call(app, "GET", "/v1/things", **bearer(old))).status_code == 401


async def test_a_token_for_another_service_is_401() -> None:
    app = app_for(identity(Platform()))
    r = await call(app, "GET", "/v1/things", **bearer(person(aud=["platform", "tools"])))
    assert r.status_code == 401


async def test_an_unknown_kid_refetches_once_then_401() -> None:
    platform = Platform()
    app = app_for(identity(platform))
    await call(app, "GET", "/v1/things", **bearer(person()))
    assert platform.jwks_calls == 1
    stranger = Ed25519Signer.generate("nobody-knows")
    token = mint({"sub": "u", "tenant_id": "t", "aud": "agents"}, stranger, ttl_s=60)
    assert (await call(app, "GET", "/v1/things", **bearer(token))).status_code == 401
    assert (await call(app, "GET", "/v1/things", **bearer(token))).status_code == 401
    assert platform.jwks_calls == 2  # one refetch for the unknown kid, not one per request


async def test_a_rotated_key_is_picked_up_by_the_refetch() -> None:
    platform = Platform()
    app = app_for(identity(platform))
    await call(app, "GET", "/v1/things", **bearer(person()))
    rotated = Ed25519Signer.generate("platform-2")
    platform.keys.append(rotated.public_jwk())
    token = mint({"sub": "usr_1", "tenant_id": "ten_a", "team_ids": ["team_a"], "aud": "agents"}, rotated, ttl_s=60)
    assert (await call(app, "GET", "/v1/things", **bearer(token))).status_code == 200


async def test_the_team_header_selects_only_among_the_tokens_teams() -> None:
    app = app_for(identity(Platform()))
    two = person(team_ids=["team_a", "team_b"], roles={"team_a": "builder", "team_b": "viewer"})
    r = await call(app, "GET", "/v1/things", **bearer(two), **{"X-Team-Id": "team_b"})
    assert r.status_code == 200 and r.json()["team_id"] == "team_b"
    r = await call(app, "GET", "/v1/things", **bearer(two), **{"X-Team-Id": "team_z"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "team_forbidden"
    r = await call(app, "GET", "/v1/things", **bearer(two))
    assert r.status_code == 400 and r.json()["error"]["code"] == "team_required"


async def test_an_api_key_is_introspected_once_and_cached_in_both_headers() -> None:
    platform = Platform()
    platform.api_keys["ok_key_1.s"] = key_principal(["read"])
    app = app_for(identity(platform))
    assert (await call(app, "GET", "/v1/things", **{"X-API-Key": "ok_key_1.s"})).status_code == 200
    r = await call(app, "GET", "/v1/things", **bearer("ok_key_1.s"))
    assert r.status_code == 200 and r.json()["kind"] == "api_key"
    assert platform.introspect_calls == 1


async def test_a_revoked_key_stops_when_the_cache_entry_expires() -> None:
    platform = Platform()
    platform.api_keys["ok_key_1.s"] = key_principal(["read"])
    app = app_for(identity(platform, key_cache_s=0))
    assert (await call(app, "GET", "/v1/things", **{"X-API-Key": "ok_key_1.s"})).status_code == 200
    del platform.api_keys["ok_key_1.s"]
    assert (await call(app, "GET", "/v1/things", **{"X-API-Key": "ok_key_1.s"})).status_code == 401


async def test_a_read_key_is_refused_on_every_write_method() -> None:
    platform = Platform()
    platform.api_keys["ok_key_r.s"] = key_principal(["read"])
    platform.api_keys["ok_key_w.s"] = key_principal(["read", "write"])
    app = app_for(identity(platform))
    r = await call(app, "POST", "/v1/things", **{"X-API-Key": "ok_key_r.s"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "scope_required"
    assert (await call(app, "POST", "/v1/things", **{"X-API-Key": "ok_key_w.s"})).status_code == 200


async def test_service_tokens_work_only_on_internal_routes() -> None:
    services = ServiceAuth(audience="agents", verifiers={SERVICES.kid: (SERVICES.verifier("agents"), "tools")})
    app = app_for(identity(Platform()), services)
    service_token = mint_service_token(SERVICES, service="tools", audience="agents", tenant_id="ten_a")
    r = await call(app, "POST", "/internal/fire", **bearer(service_token))
    assert r.status_code == 200 and r.json()["kind"] == "service" and r.json()["tenant_id"] == "ten_a"
    assert (await call(app, "GET", "/v1/things", **bearer(service_token))).status_code == 401
    assert (await call(app, "POST", "/internal/fire", **bearer(person()))).status_code == 401
    other = mint_service_token(SERVICES, service="tools", audience="models", tenant_id="ten_a")
    assert (await call(app, "POST", "/internal/fire", **bearer(other))).status_code == 401


async def test_dev_mode_is_honoured_only_in_dev() -> None:
    dev = app_for(identity(Platform(), dev_user={"sub": "usr_dev", "email": "dev@bank.test", "name": "Dev"}))
    r = await call(dev, "GET", "/v1/things", **{"X-Dev-User": "maya@bank.test"})
    assert r.status_code == 200 and r.json()["auth_method"] == "dev" and r.json()["email"] == "maya@bank.test"
    platform_mode = app_for(identity(Platform()))
    assert (await call(platform_mode, "GET", "/v1/things", **{"X-Dev-User": "maya@bank.test"})).status_code == 401


def test_a_service_cannot_build_an_identity_without_an_audience() -> None:
    with pytest.raises(ValueError):
        Identity(audience="", jwks=Platform().jwks, introspect=Platform().introspect)


async def test_a_person_token_is_refused_internally_even_if_one_key_signs_both() -> None:
    """A deployment that reuses the user key for services must still not let a person's token through an internal
    route: the token's kind decides, not only which key signed it."""
    shared = ServiceAuth(audience="agents", verifiers={ISSUER.kid: (ISSUER.verifier("agents"), None)})
    app = app_for(identity(Platform()), shared)
    assert (await call(app, "POST", "/internal/fire", **bearer(person()))).status_code == 401
