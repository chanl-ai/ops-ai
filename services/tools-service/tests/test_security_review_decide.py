"""Who decides a module's security review (c-040), through the real routes with people signed in on platform-style
tokens: only an approver or admin on the Security team, never the requester."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_policy import Ed25519Signer, mint
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import build_app, response_checker

PLATFORM = Ed25519Signer.generate("platform-test")
HOST = "statements.example.com"


def person(tenant: str, name: str, roles: dict[str, str]) -> dict[str, str]:
    team = next(iter(roles))
    claims = {
        "sub": f"usr_{name.split(maxsplit=1)[0].lower()}",
        "email": f"{name.split(maxsplit=1)[0].lower()}@bank.example",
        "name": name,
        "kind": "person",
        "aud": ["tools"],
        "tenant_id": tenant,
        "team_ids": list(roles),
        "roles": roles,
        # As platform-service's dev sign-in issues them: the role rule must hold for these too.
        "auth_method": "dev",
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=300)}", "X-Team-Id": team}


async def jwks() -> dict[str, Any]:
    return {"keys": [PLATFORM.public_jwk()]}


async def introspect(_key: str) -> dict[str, Any] | None:
    return None


@pytest.fixture
async def signed_in(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, dict[str, str]]]]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools")),
    )
    app = build_app(engine, seed, tenant, auth=auth)
    people = {
        "james": person(tenant, "James Richardson", {"team_platform": "builder"}),
        "maya": person(tenant, "Maya Okafor", {"team_platform": "approver"}),
        "nadia": person(tenant, "Nadia Petrov", {"team_security": "approver"}),
    }
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        r = await c.post("/v1/egress/hosts", json={"value": HOST}, headers=people["james"])
        assert r.status_code in (200, 201), r.text
        yield c, people


async def _reviewed_module(c: httpx.AsyncClient, james: dict[str, str], name: str) -> tuple[str, str]:
    made = await c.post(
        "/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}, headers=james
    )
    mid = made.json()["data"]["id"]
    op = {
        "name": f"{name.replace('-', '_')}_get",
        "description": "",
        "access": "read",
        "method": "GET",
        "url": f"https://{HOST}/v1/x",
    }
    assert (await c.post(f"/v1/tool-modules/{mid}/operations", json=op, headers=james)).status_code == 200
    reviewed = (await c.post(f"/v1/tool-modules/{mid}/reviews", json={"note": "c-040"}, headers=james)).json()["data"]
    return mid, next(r["id"] for r in reviewed["reviews"] if r["decision"] == "pending")


async def test_only_securitys_approver_decides_never_the_requester_or_another_teams_approver(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, people = signed_in
    mid, rid = await _reviewed_module(c, people["james"], "c040-statements")
    decide = f"/v1/tool-modules/{mid}/reviews/{rid}/decide"
    own = await c.post(decide, json={"decision": "approved"}, headers=people["james"])
    assert own.status_code == 403 and "You requested this review" in own.json()["error"]["message"]
    elsewhere = await c.post(decide, json={"decision": "approved"}, headers=people["maya"])
    assert elsewhere.status_code == 403 and "Security team" in elsewhere.json()["error"]["message"]
    approved = await c.post(decide, json={"decision": "approved"}, headers=people["nadia"])
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["status"] == "published"


async def test_security_requests_changes_only_with_a_reason_and_a_new_module_goes_back_to_draft(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, people = signed_in
    mid, rid = await _reviewed_module(c, people["james"], "c040-holds")
    decide = f"/v1/tool-modules/{mid}/reviews/{rid}/decide"
    bare = await c.post(decide, json={"decision": "changes_requested"}, headers=people["nadia"])
    assert bare.status_code == 400
    why = ["place_hold must need an approval token"]
    changed = await c.post(decide, json={"decision": "changes_requested", "findings": why}, headers=people["nadia"])
    detail = changed.json()["data"]
    assert changed.status_code == 200 and detail["status"] == "draft"
    assert next(r for r in detail["reviews"] if r["id"] == rid)["findings"] == why


async def test_the_security_review_view_lists_pending_reviews_and_drops_decided_ones(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, people = signed_in
    mid, rid = await _reviewed_module(c, people["james"], "c040-cards")
    listed = (
        await c.get("/v1/tool-modules", params={"view": "security_review", "pageSize": 100}, headers=people["nadia"])
    ).json()["data"]
    row = next((m for m in listed["data"] if m["id"] == mid), None)
    assert (
        row is not None
        and row["pendingReview"]["requestedBy"] == "James Richardson"
        and row["pendingReview"]["id"] == rid
    )
    assert listed["viewCounts"]["security_review"] >= 1
    await c.post(f"/v1/tool-modules/{mid}/reviews/{rid}/decide", json={"decision": "approved"}, headers=people["nadia"])
    after = (
        await c.get("/v1/tool-modules", params={"view": "security_review", "pageSize": 100}, headers=people["nadia"])
    ).json()["data"]
    assert all(m["id"] != mid for m in after["data"])
