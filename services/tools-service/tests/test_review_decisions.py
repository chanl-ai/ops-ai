"""A module's review is a publish request in agents-service's Reviews (c-163); tools-service opens it for the person and
applies the decision Reviews sends. Who may decide (Security, never the requester or saver) is agents-service's rule
and its tests. By failure mode here: a person or another service applying a decision, a review opened without the
person's credentials or team, a version left waiting when no review opened, and the queue's view out of step."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import Ed25519Signer, mint
from ops_service_kit.errors import ServiceUnavailable
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import FakeReviews, build_app, response_checker, service_headers

PLATFORM = Ed25519Signer.generate("platform-test")
HOST = "statements.example.com"
REVIEWS = FakeReviews()


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
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


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
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, reviews=REVIEWS)
    people = {
        "james": person(tenant, "James Richardson", {"team_platform": "builder"}),
        "maya": person(tenant, "Maya Okafor", {"team_platform": "approver"}),
        "nadia": person(tenant, "Nadia Petrov", {"team_security": "approver"}),
    }
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    hooks = {"response": [response_checker(app)]}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://tools", event_hooks=hooks
    ) as c:
        r = await c.post("/v1/egress/hosts", json={"value": HOST}, headers=sam)
        assert r.status_code in (200, 201), r.text
        yield c, people


async def _reviewed_module(c: httpx.AsyncClient, james: dict[str, str], name: str) -> tuple[str, dict[str, Any]]:
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
    reviewed = await c.post(f"/v1/tool-modules/{mid}/reviews", json={"note": "c-163"}, headers=james)
    assert reviewed.status_code == 200, reviewed.text
    return mid, next(v for v in reviewed.json()["data"]["versions"] if v["status"] == "in_review")


def _decision(v: dict[str, Any], decision: str = "approved", reason: str | None = None) -> dict[str, Any]:
    return {"requestId": v["reviewId"], "version": v["version"], "decision": decision, "reason": reason, "by": "Nadia"}


async def test_only_agents_service_applies_a_decision(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = signed_in
    mid, v = await _reviewed_module(c, people["james"], "c163-statements")
    url = f"/v1/tool-modules/{mid}/review-decisions"
    person = await c.post(url, json=_decision(v), headers=people["nadia"])
    assert person.status_code in (401, 403), person.text
    other = await c.post(url, json=_decision(v), headers=service_headers(tenant, "kb"))
    assert other.status_code == 403 and other.json()["error"]["code"] == "service_required", other.text
    applied = await c.post(url, json=_decision(v), headers=service_headers(tenant))
    assert applied.status_code == 200 and applied.json()["data"]["status"] == "published", applied.text


async def test_the_review_opens_with_the_persons_credentials_and_team(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, people = signed_in
    REVIEWS.opened.clear()
    _, v = await _reviewed_module(c, people["james"], "c163-cards")
    sent = REVIEWS.opened[-1]
    assert sent["credentials"]["authorization"] == people["james"]["Authorization"]
    assert sent["team_id"] == "team_platform" and v["reviewId"] == f"TMP-{1000 + len(REVIEWS.opened)}"


async def test_no_version_waits_when_reviews_refuses(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    class Down(FakeReviews):
        async def open(self, credentials: dict[str, str], **kw: Any) -> str:
            raise ServiceUnavailable("Reviews is down.", code="reviews_unavailable")

    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    app = build_app(engine, seed, tenant, reviews=Down())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        before = (await c.get("/v1/tool-modules/mod_core_banking")).json()["data"]
        write = next(o for o in before["operations"] if o["access"] == "write" and o["requiresApproval"])
        staged = await c.patch(
            f"/v1/tool-modules/mod_core_banking/operations/{write['id']}", json={"requiresApproval": False}
        )
        assert staged.status_code == 200, staged.text
        refused = await c.post("/v1/tool-modules/mod_core_banking/versions", json={"note": "Writes run unattended"})
        assert refused.status_code == 503, refused.text
        after = (await c.get("/v1/tool-modules/mod_core_banking")).json()["data"]
        assert (after["version"], len(after["versions"])) == (before["version"], len(before["versions"]))
        assert all(x["status"] != "in_review" for x in after["versions"])


async def test_a_return_sends_a_new_module_back_to_draft_with_the_reason(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = signed_in
    mid, v = await _reviewed_module(c, people["james"], "c163-holds")
    why = "place_hold must need an approval token"
    r = await c.post(
        f"/v1/tool-modules/{mid}/review-decisions", json=_decision(v, "returned", why), headers=service_headers(tenant)
    )
    detail = r.json()["data"]
    assert r.status_code == 200 and detail["status"] == "draft", r.text
    assert next(x for x in detail["versions"] if x["version"] == v["version"])["finding"] == why


async def test_the_security_review_view_lists_pending_reviews_and_drops_decided_ones(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    c, people = signed_in
    mid, v = await _reviewed_module(c, people["james"], "c163-ledger")
    params = {"view": "security_review", "pageSize": 100}
    listed = (await c.get("/v1/tool-modules", params=params, headers=people["nadia"])).json()["data"]
    row = next((m for m in listed["data"] if m["id"] == mid), None)
    assert row is not None and row["pendingReview"] == {
        "id": v["reviewId"],
        "version": v["version"],
        "requestedBy": "James Richardson",
        "requestedAt": v["requestedAt"],
    }
    await c.post(f"/v1/tool-modules/{mid}/review-decisions", json=_decision(v), headers=service_headers(tenant))
    after = (await c.get("/v1/tool-modules", params=params, headers=people["nadia"])).json()["data"]
    assert all(m["id"] != mid for m in after["data"])
