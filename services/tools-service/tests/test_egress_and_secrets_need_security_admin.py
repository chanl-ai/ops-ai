"""Who may change the tenant's egress allow-list and tool secrets (c-079), through the real routes with people signed
in on platform-style tokens: only an admin on the Security team. A builder or an admin of another team would otherwise
widen what every module may reach, or swap the credentials it calls with."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker
from .test_review_decisions import introspect, jwks, person

CHANGES = (
    ("post", "/v1/egress/hosts", {"value": "ledger.example.com"}),
    ("post", "/v1/egress/hosts/remove", {"value": "ledger.example.com"}),
    ("post", "/v1/egress/ranges", {"value": "10.20.0.0/16"}),
    ("post", "/v1/egress/ranges/remove", {"value": "10.20.0.0/16"}),
    ("post", "/v1/secrets", {"name": "LEDGER_TOKEN", "value": "s3cret"}),
    ("post", "/v1/secrets/LEDGER_TOKEN/rotate", {"value": "s3cret-2"}),
    ("delete", "/v1/secrets/LEDGER_TOKEN", None),
)


@pytest.fixture
async def client(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools")),
    )
    app = build_app(engine, seed, tenant, auth=auth)
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        yield c


async def _send(c: httpx.AsyncClient, method: str, path: str, body: Any, who: dict[str, str]) -> httpx.Response:
    return await c.request(method, path, json=body, headers=who)


@pytest.mark.parametrize(
    "roles",
    [{"team_platform": "builder"}, {"team_platform": "admin"}, {"team_security": "approver"}],
    ids=["builder", "admin-of-another-team", "security-approver"],
)
async def test_only_a_security_admin_changes_egress_and_secrets(
    client: httpx.AsyncClient, tenant: str, roles: dict[str, str]
) -> None:
    other = person(tenant, "James Richardson", roles)
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    for method, path, body in CHANGES:
        refused = await _send(client, method, path, body, other)
        assert refused.status_code == 403, f"{method} {path}: {refused.status_code} {refused.text}"
        assert refused.json()["error"]["code"] == "not_security_admin"
        done = await _send(client, method, path, body, sam)
        assert done.status_code in (200, 201, 204), f"{method} {path}: {done.status_code} {done.text}"
    # Reading stays open: every builder sees what modules may reach and which secret names exist.
    assert (await client.get("/v1/egress", headers=other)).status_code == 200
    assert (await client.get("/v1/secrets", headers=other)).status_code == 200
