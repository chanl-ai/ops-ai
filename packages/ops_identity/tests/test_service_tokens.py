"""Service tokens between services (I13), by failure mode: a service key mints a token naming another service, a kid
nobody trusts is accepted, a tenant-scoped mount takes a token with no tenant, the dev key works outside dev, and a
caller reuses one token past its life instead of minting per call."""

# No `from __future__ import annotations`: the test routes name local objects in Depends().

from typing import Annotated, Any

import httpx
import pytest
from fastapi import Depends, FastAPI
from pydantic import SecretStr

from ops_identity import (
    Principal,
    ServiceAuth,
    http_introspect,
    mint_service_token,
    service_signer,
    service_verifiers,
)
from ops_policy import Ed25519Signer
from ops_service_kit.http import install_error_handlers
from ops_service_kit.settings import Settings

AGENTS = Ed25519Signer.generate("svc-agents-1")


def app_for(services: ServiceAuth) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/internal/introspect")
    async def introspect(p: Annotated[Principal, Depends(services.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    return app


async def post(app: FastAPI, token: str) -> httpx.Response:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://p") as c:
        return await c.post("/internal/introspect", headers={"Authorization": f"Bearer {token}"})


def platform_trusting_agents(*, tenant_scoped: bool) -> FastAPI:
    trusted = {AGENTS.kid: (AGENTS.verifier("platform"), "agents")}
    return app_for(ServiceAuth(audience="platform", verifiers=trusted, tenant_scoped=tenant_scoped))


async def test_a_service_key_proves_which_service_is_calling() -> None:
    app = platform_trusting_agents(tenant_scoped=False)
    ok = mint_service_token(AGENTS, service="agents", audience="platform", tenant_id=None)
    r = await post(app, ok)
    assert r.status_code == 200 and r.json()["sub"] == "service:agents"
    impostor = mint_service_token(AGENTS, service="tools", audience="platform", tenant_id=None)
    assert (await post(app, impostor)).status_code == 401


async def test_a_kid_nobody_trusts_is_refused() -> None:
    stranger = Ed25519Signer.generate("svc-stranger-1")
    token = mint_service_token(stranger, service="agents", audience="platform", tenant_id=None)
    assert (await post(platform_trusting_agents(tenant_scoped=False), token)).status_code == 401


async def test_a_tenant_scoped_mount_needs_a_tenant_and_introspect_does_not() -> None:
    no_tenant = mint_service_token(AGENTS, service="agents", audience="platform", tenant_id=None)
    assert (await post(platform_trusting_agents(tenant_scoped=True), no_tenant)).status_code == 401
    with_tenant = mint_service_token(AGENTS, service="agents", audience="platform", tenant_id="ten_a")
    r = await post(platform_trusting_agents(tenant_scoped=True), with_tenant)
    assert r.status_code == 200 and r.json()["tenant_id"] == "ten_a"


def test_settings_keys_bind_each_kid_to_one_service() -> None:
    settings = Settings(
        service_signing_key=SecretStr(AGENTS.private_text()),
        service_signing_kid="svc-agents-1",
        service_public_keys={"svc-agents-1": {"service": "agents", "x": AGENTS.public_jwk()["x"]}},
    )
    assert service_signer(settings).kid == "svc-agents-1"
    verifiers = service_verifiers(settings, "platform")
    assert verifiers["svc-agents-1"][1] == "agents"
    assert "svc-dev" in verifiers  # environment is dev here


def test_the_dev_key_is_refused_outside_dev() -> None:
    # model_copy skips validation, which would otherwise refuse a production Settings without its secrets.
    settings = Settings().model_copy(update={"environment": "production", "service_signing_key": None})
    with pytest.raises(ValueError):
        service_signer(settings)
    assert "svc-dev" not in service_verifiers(settings, "platform")


async def test_introspect_mints_a_fresh_token_per_call() -> None:
    minted: list[str] = []

    def token() -> str:
        t = mint_service_token(AGENTS, service="agents", audience="platform", tenant_id=None)
        minted.append(t)
        return t

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"].removeprefix("Bearer "))
        return httpx.Response(401)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://p") as c:
        introspect = http_introspect(c, "/v1/auth/introspect", token)
        assert await introspect("ok_a.b") is None
        assert await introspect("ok_a.b") is None
    assert seen == minted and len(minted) == 2
