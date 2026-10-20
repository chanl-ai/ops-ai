"""ops_identity against the real platform-service: a service built on it fetches the key set and introspects keys
over HTTP, so the token platform issues, the key it mints and the revocation it records are what the service sees."""

# No `from __future__ import annotations`: the route below names a local Identity in Depends().

from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI

from ops_identity import Identity, Principal, http_introspect, http_jwks
from ops_service_kit.http import install_error_handlers

from .conftest import SERVICE_TOKEN, Platform
from .test_members import as_admin


def service(platform: Platform) -> FastAPI:
    identity = Identity(
        audience="agents",
        jwks=http_jwks(platform.public, "/.well-known/jwks.json"),
        introspect=http_introspect(platform.internal, "/v1/auth/introspect", SERVICE_TOKEN),
        key_cache_s=0,
    )
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/v1/agents")
    async def agents(p: Annotated[Principal, Depends(identity.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    @app.post("/v1/agents")
    async def create(p: Annotated[Principal, Depends(identity.principal)]) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return p.model_dump()

    return app


async def test_a_signed_in_person_and_their_key_resolve_at_another_service(platform: Platform) -> None:
    admin, h = await as_admin(platform)
    made = (await platform.public.post("/v1/api-keys", headers=h, json={"name": "ci", "scopes": ["read"]})).json()[
        "data"
    ]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service(platform)), base_url="http://agents") as c:
        r = await c.get("/v1/agents", headers={"Authorization": h["Authorization"]})
        assert r.status_code == 200, r.text
        assert (r.json()["tenant_id"], r.json()["team_id"]) == (admin.tenant_id, h["X-Team-Id"])
        key = {"Authorization": f"Bearer {made['secret']}"}
        assert (await c.get("/v1/agents", headers=key)).json()["kind"] == "api_key"
        assert (await c.post("/v1/agents", headers=key)).status_code == 403
        await platform.public.post(f"/v1/api-keys/{made['key']['id']}/revoke", headers=h)
        assert (await c.get("/v1/agents", headers=key)).status_code == 401
