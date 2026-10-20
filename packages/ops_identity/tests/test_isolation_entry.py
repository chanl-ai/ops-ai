"""The isolation context a request enters (c-409), through the real dependency with real tokens, by failure mode: a
person, key or team-bound service token acting for every team; a service token with no team acting with no reason; a
platform session with no roles taken for the dev header caller; the dev header caller narrowed to one team; and a
tenant named in the body or a header reaching the context."""

# No `from __future__ import annotations`: the test route names local objects in Depends().

from typing import Any

from fastapi import Body, FastAPI
from httpx import ASGITransport, AsyncClient

from ops_identity import Auth, CurrentCaller, CurrentService, Identity, ServiceAuth, install_auth, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.http import install_error_handlers
from ops_store import isolation
from ops_store.team_scope import acting_team

ISSUER = Ed25519Signer.generate("platform-1")
SERVICES = Ed25519Signer.generate("services-1")


def person(**claims: Any) -> str:
    body = {
        "sub": "usr_1",
        "email": "a@bank.test",
        "name": "Ana",
        "tenant_id": "ten_a",
        "team_ids": ["team_a", "team_b"],
        "roles": {"team_a": "builder", "team_b": "viewer"},
        "kind": "person",
        "auth_method": "session",
        "aud": ["agents"],
        **claims,
    }
    return mint(body, ISSUER, ttl_s=TEST_TOKEN_TTL_S)


async def _jwks() -> dict[str, Any]:
    return {"keys": [ISSUER.public_jwk()]}


async def _introspect(key: str) -> dict[str, Any] | None:
    if key != "ok_team_key":
        return None
    return {"sub": "usr_k", "tenantId": "ten_a", "teamId": "team_b", "scopes": ["read", "write"]}


def services() -> ServiceAuth:
    return ServiceAuth(
        audience="agents",
        verifiers={SERVICES.kid: (SERVICES.verifier("agents"), None)},
        scopes={"provisioner": ["agents:view"]},
    )


def platform_app() -> FastAPI:
    auth = Auth(Identity(audience="agents", jwks=_jwks, introspect=_introspect, services=services()), services())
    return _app(auth)


def dev_app() -> FastAPI:
    dev_user = {"sub": "usr_dev", "email": "dev@bank.test", "name": "Dev", "tenant_id": "local", "team_id": "team_ops"}
    identity = Identity(audience="agents", jwks=_jwks, introspect=_introspect, dev_user=dev_user, services=services())
    return _app(Auth(identity, services()))


def _app(auth: Auth) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    install_auth(app, auth)

    @app.post("/seen")
    async def seen(p: CurrentCaller, body: dict[str, Any] = Body(default_factory=dict)) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]  # noqa: B008
        return _ctx()

    @app.post("/internal")
    async def internal(p: CurrentService) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return _ctx()

    return app


def _ctx() -> dict[str, Any]:
    ctx = isolation.current()
    return {
        "tenant": ctx.tenant_id,
        "team": ctx.team_id,
        "scope": ctx.scope,
        "reason": ctx.reason,
        "acting": acting_team(),
    }


async def seen(
    app: FastAPI, headers: dict[str, str], body: dict[str, Any] | None = None, path: str = "/seen"
) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(path, json=body or {}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def service_token(team: str | None) -> str:
    return mint_service_token(
        SERVICES, service="provisioner", audience="agents", tenant_id="ten_a", scopes=["agents:view"], team_id=team
    )


async def test_a_person_acts_in_the_team_they_chose_and_nowhere_wider() -> None:
    got = await seen(platform_app(), {"Authorization": f"Bearer {person()}", "X-Team-Id": "team_b"})
    assert got == {"tenant": "ten_a", "team": "team_b", "scope": "team", "reason": None, "acting": "team_b"}


async def test_an_api_key_acts_in_its_own_team() -> None:
    got = await seen(platform_app(), {"X-API-Key": "ok_team_key"})
    assert (got["tenant"], got["team"], got["scope"]) == ("ten_a", "team_b", "team")


async def test_a_service_token_with_a_team_acts_in_that_team() -> None:
    got = await seen(platform_app(), {"Authorization": f"Bearer {service_token('team_a')}"})
    assert (got["team"], got["scope"], got["reason"]) == ("team_a", "team", None)


async def test_a_service_token_with_no_team_acts_for_the_tenant_naming_the_service() -> None:
    got = await seen(platform_app(), {"Authorization": f"Bearer {service_token(None)}"}, path="/internal")
    assert got == {"tenant": "ten_a", "team": None, "scope": "tenant", "reason": "service:provisioner", "acting": None}


async def test_a_platform_session_with_no_roles_is_not_the_dev_caller() -> None:
    token = person(auth_method="dev", roles={}, team_ids=["team_a"])
    got = await seen(platform_app(), {"Authorization": f"Bearer {token}"})
    assert (got["team"], got["scope"], got["reason"]) == ("team_a", "team", None)


async def test_the_dev_header_caller_acts_for_every_team_with_reason_dev() -> None:
    got = await seen(dev_app(), {"X-Team-Id": "team_cards"})
    assert got == {"tenant": "local", "team": None, "scope": "tenant", "reason": "dev", "acting": None}


async def test_a_tenant_in_the_body_or_a_header_never_reaches_the_context() -> None:
    got = await seen(
        platform_app(),
        {"Authorization": f"Bearer {person()}", "X-Team-Id": "team_a", "X-Tenant-Id": "ten_b"},
        {"tenant_id": "ten_b", "tenantId": "ten_b", "team_id": "team_x"},
    )
    assert (got["tenant"], got["team"]) == ("ten_a", "team_a")
