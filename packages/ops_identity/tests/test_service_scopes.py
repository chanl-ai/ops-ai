"""Service tokens with scopes (c-167), by failure mode: a service minting itself a scope it was never given, the dev
key passing any scope, a service token reaching a route that decides on roles, a service on a public route without a
team or naming another team in a header. Tokens are real, routes are real FastAPI apps built by `Auth.for_dev`, as
every service builds them."""

# No `from __future__ import annotations`: the test routes name local objects in Depends().

import httpx
from fastapi import FastAPI

from ops_identity import Auth, CurrentCaller, CurrentPrincipal, CurrentService, install_auth, mint_service_token
from ops_identity.service_keys import dev_service_signer
from ops_service_kit.http import install_error_handlers
from ops_service_kit.settings import Settings


def app() -> FastAPI:
    a = FastAPI()
    install_error_handlers(a)
    install_auth(
        a, Auth.for_dev(Settings(environment="dev", auth_mode="dev"), audience="files", name="Dev", email="d@x")
    )

    @a.post("/v1/people-only")
    async def people_only(p: CurrentPrincipal) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"kind": p.kind}

    @a.post("/v1/callers")
    async def callers(p: CurrentCaller) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {"kind": p.kind, "team": p.team_id, "scopes": p.scopes}

    @a.post("/v1/internal/thing")
    async def internal(p: CurrentService) -> dict[str, object]:  # pyright: ignore[reportUnusedFunction]
        return {"scopes": p.scopes}

    return a


def token(service: str, scopes: list[str], team: str | None = "team_ops") -> dict[str, str]:
    t = mint_service_token(
        dev_service_signer(), service=service, audience="files", tenant_id="ten_a", scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {t}"}


async def call(path: str, headers: dict[str, str]) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://t") as c:
        return await c.post(path, headers=headers)


async def test_a_service_cannot_mint_itself_a_scope_it_was_not_given() -> None:
    assert (await call("/v1/internal/thing", token("scanner", ["files:decide"]))).status_code == 200
    # The dev key signs for any service name, and is capped by that name's scopes all the same.
    assert (await call("/v1/internal/thing", token("kb", ["files:decide"]))).status_code == 401
    assert (await call("/v1/callers", token("kb", ["files:decide"]))).status_code == 401


async def test_a_route_that_decides_on_roles_refuses_a_service() -> None:
    r = await call("/v1/people-only", token("scanner", ["files:decide"]))
    assert r.status_code == 403 and r.json()["error"]["code"] == "scope_required"


async def test_a_service_on_a_public_route_acts_in_its_signed_team_only() -> None:
    ok = await call("/v1/callers", token("scanner", ["files:decide"]))
    assert ok.status_code == 200 and ok.json() == {"kind": "service", "team": "team_ops", "scopes": ["files:decide"]}
    teamless = await call("/v1/callers", token("scanner", ["files:decide"], team=None))
    assert teamless.status_code == 403 and teamless.json()["error"]["code"] == "team_required"
    other = await call("/v1/callers", {**token("scanner", ["files:decide"]), "X-Team-Id": "team_fraud"})
    assert other.status_code == 403 and other.json()["error"]["code"] == "team_forbidden"
