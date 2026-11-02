"""An app's first address on a host the tenant has not listed asks Security instead of failing (c-616 S13). Who may
decide the task and how it lists in Human Tasks are agents-service's rules and uc-617's walk. By failure mode here:
something saved while the host waits, a refused host asked about again, someone other than agents-service listing a
host through the decision route, and a Security admin asked to approve their own change (roles decide: they list it)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.egress import EgressStore
from ops_tools.store.modules import ModuleStore

from .conftest import Api, FakeReviews, build_app, service_headers

# The signed-in people's app, a fixture, used by name below.
from .test_review_decisions import (
    REVIEWS,
    introspect,
    jwks,
    person,
    signed_in,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

OP = {
    "name": "get_statement",
    "description": "Monthly statement",
    "access": "read",
    "method": "GET",
    "url": "https://unlisted-statements.example.com/v1/accounts/{accountId}/statement",
}


def _blank(name: str) -> dict[str, str]:
    return {"displayName": name, "name": name, "type": "http"}


async def test_an_unlisted_host_is_held_for_security_and_nothing_is_saved(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
) -> None:
    c, people = signed_in
    REVIEWS.hosts.clear()
    made = await c.post("/v1/tool-modules/blank", json=_blank("s13-held"), headers=people["james"])
    mid = made.json()["data"]["id"]
    held = await c.post(f"/v1/tool-modules/{mid}/operations", json=OP, headers=people["james"])
    assert held.status_code == 202, held.text
    run_key = held.json()["data"]["runKey"]
    assert held.json()["data"] == {"heldFor": "security", "host": "unlisted-statements.example.com", "runKey": run_key}
    again = await c.post(f"/v1/tool-modules/{mid}/operations", json=OP, headers=people["james"])
    assert again.json()["data"]["runKey"] == run_key, "a second attempt waits on the same task"
    after = (await c.get(f"/v1/tool-modules/{mid}", headers=people["james"])).json()["data"]
    assert after["operations"] == [] and "unlisted-statements.example.com" not in after["egressHosts"]


async def test_a_security_admin_lists_the_host_in_their_own_name_without_a_task(
    signed_in: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    c, _ = signed_in
    sam = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    REVIEWS.hosts.clear()
    made = await c.post("/v1/tool-modules/blank", json=_blank("s13-listed"), headers=sam)
    mid = made.json()["data"]["id"]
    added = await c.post(f"/v1/tool-modules/{mid}/operations", json=OP, headers=sam)
    assert added.status_code == 200, added.text
    assert REVIEWS.hosts == [], "no task for someone who holds the approver role"
    trail = [(a["value"], a["action"], a["actor"]) for a in await EgressStore(engine).audit(tenant)]
    assert ("unlisted-statements.example.com", "added", "Sam Adeyemi") in trail


async def test_a_refused_host_is_refused_with_securitys_reason(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    class Refused(FakeReviews):
        async def open_host(self, credentials: dict[str, str], **kw: Any) -> dict[str, Any]:
            return {"id": "EGH-1001", "status": "rejected", "decisionReason": "not a bank system"}

    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, reviews=Refused())
    james = person(tenant, "James Richardson", {"team_platform": "builder"})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        made = await c.post("/v1/tool-modules/blank", json=_blank("s13-refused"), headers=james)
        mid = made.json()["data"]["id"]
        r = await c.post(f"/v1/tool-modules/{mid}/operations", json=OP, headers=james)
    assert r.status_code == 422, r.text
    error = r.json()["error"]
    assert error["code"] == "egress_host_refused"
    assert "not a bank system" in error["message"] and "EGH-1001" in error["message"]


async def test_only_agents_service_lists_an_approved_host(api: Api) -> None:
    decision = {
        "requestId": "EGH-1001",
        "host": "unlisted-statements.example.com",
        "decision": "approved",
        "by": "Sam Adeyemi",
    }
    by_person = await api.client.post("/v1/egress/held-hosts/decisions", json=decision)
    assert by_person.status_code in (401, 403), by_person.text
    by_other = await api.client.post(
        "/v1/egress/held-hosts/decisions",
        json=decision,
        headers=service_headers(api.tenant, "platform", scopes=["secrets_egress:manage"]),
    )
    assert by_other.status_code in (401, 403), by_other.text
    without_scope = await api.client.post(
        "/v1/egress/held-hosts/decisions", json=decision, headers=service_headers(api.tenant)
    )
    assert without_scope.status_code == 403, "agents-service's ordinary token does not list hosts"
    listed = await api.client.post(
        "/v1/egress/held-hosts/decisions",
        json=decision,
        headers=service_headers(api.tenant, scopes=["secrets_egress:manage"]),
    )
    assert listed.status_code == 200 and listed.json()["data"]["changed"] is True, listed.text
    hosts = (await api.client.get("/v1/egress")).json()["data"]["hosts"]
    assert {h["host"]: h["addedBy"] for h in hosts}["unlisted-statements.example.com"] == "Sam Adeyemi"
    added = await api.call("POST", "/mod_document_service/operations", json=OP)
    assert added.status_code == 200, "the retry after approval saves"
