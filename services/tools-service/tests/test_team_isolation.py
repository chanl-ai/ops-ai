"""A tool module is its team's: a person outside the owning team does not see it listed and reads it by
id as 404, unless it is approved for one of their team's workflows, the explicit grant across teams. By failure mode,
with tokens minted as platform-service mints them:

- the list shows another team's module;
- a read by id answers 200 (or 403 naming the owner);
- a module made in a team the dev seed does not hold is stored as the all-scope team's, so its own team loses it;
- a name another team holds is refused in this team, or 500 instead of a second copy;
- the explicit grant stops working;
- another service's grant list, which a run's grants decide, loses another team's operations.
"""

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

from .conftest import FakeReviews, build_app, service_headers
from .test_review_decisions import introspect, jwks, person

# A team made on the Teams page: the dev seed's directory does not hold it.
NEW_TEAM = "team_d90630bcb0e7"


@pytest.fixture
async def people(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, dict[str, str]]]]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    app = build_app(engine, seed, tenant, auth=auth, reviews=FakeReviews())
    who = {
        "builder": person(tenant, "Nora Builder", {NEW_TEAM: "builder"}),
        "outsider": person(tenant, "Omar Outsider", {"team_cards": "admin"}),
        "security": person(tenant, "Sam Security", {"team_security": "admin"}),
        "lending": person(tenant, "Lena Lending", {"team_lending": "viewer"}),
        "platform": person(tenant, "Pat Platform", {"team_platform": "viewer"}),
    }
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        yield c, who


async def _made(c: httpx.AsyncClient, who: dict[str, str], name: str) -> dict[str, Any]:
    r = await c.post("/v1/tool-modules/blank", json={"displayName": name, "name": name, "type": "http"}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _ids(r: httpx.Response) -> list[str]:
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()["data"]["data"]]


async def test_a_module_made_in_a_new_team_is_that_teams_and_listed_to_it(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, who = people
    made = await _made(c, who["builder"], "nf-ledger")
    assert made["id"] in _ids(await c.get("/v1/tool-modules", params={"pageSize": 100}, headers=who["builder"]))
    assert (await c.get(f"/v1/tool-modules/{made['id']}", headers=who["builder"])).status_code == 200
    # Stored under the new team's id, so the dev seed's all-scope team does not hold it.
    assert (await c.get(f"/v1/tool-modules/{made['id']}", headers=who["platform"])).status_code == 404


async def test_another_teams_module_is_not_listed_even_to_security(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, who = people
    made = await _made(c, who["builder"], "nf-cards")
    for outside in ("outsider", "security"):
        listed = _ids(await c.get("/v1/tool-modules", params={"pageSize": 100}, headers=who[outside]))
        assert made["id"] not in listed, outside


async def test_another_teams_module_answers_404_by_id(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, who = people
    made = await _made(c, who["builder"], "nf-hold")
    for path in (f"/v1/tool-modules/{made['id']}", f"/v1/tool-modules/{made['id']}/activity"):
        r = await c.get(path, headers=who["outsider"])
        assert r.status_code == 404, f"{path}: {r.text}"


async def test_two_teams_each_own_a_module_of_the_same_name_and_neither_sees_the_other(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    c, who = people
    theirs = await _made(c, who["builder"], "nf-shared-name")
    mine = await _made(c, who["outsider"], "nf-shared-name")
    assert mine["id"] != theirs["id"]
    assert mine["id"] in _ids(await c.get("/v1/tool-modules", params={"pageSize": 100}, headers=who["outsider"]))
    assert theirs["id"] not in _ids(await c.get("/v1/tool-modules", params={"pageSize": 100}, headers=who["outsider"]))
    assert (await c.get(f"/v1/tool-modules/{theirs['id']}", headers=who["outsider"])).status_code == 404
    assert (await c.get(f"/v1/tool-modules/{mine['id']}", headers=who["builder"])).status_code == 404


async def test_a_module_approved_for_a_teams_workflow_is_read_by_that_team(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],
) -> None:
    # The seed's Core Banking Platform has a Lending workflow's approval: the explicit grant across teams.
    c, who = people
    assert "mod_core_banking" in _ids(await c.get("/v1/tool-modules", params={"pageSize": 100}, headers=who["lending"]))
    assert (await c.get("/v1/tool-modules/mod_core_banking", headers=who["lending"])).status_code == 200
    assert (await c.get("/v1/tool-modules/mod_payments_hub", headers=who["lending"])).status_code == 404


async def test_a_team_holding_only_a_workflow_grant_changes_nothing_of_the_module(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    # Lending reads Core Banking through its workflow's grant; every write answers as for a module it cannot see.
    c, _ = people
    owner = person(tenant, "Pat Platform", {"team_platform": "admin"})
    lending = person(tenant, "Lena Lending", {"team_lending": "admin"})
    base = "/v1/tool-modules/mod_core_banking"
    before = (await c.get(base, headers=owner)).json()["data"]
    op = before["operations"][0]["id"]
    grant = next(a["id"] for a in before["approvals"] if a["status"] == "approved")
    mock = await c.post(f"{base}/operations/{op}/mocks", json={"name": "Owner's answer"}, headers=owner)
    assert mock.status_code == 201, mock.text
    mock_id = mock.json()["data"]["id"]
    get = await c.get(f"{base}/operations/{op}/mocks", headers=owner)
    held = (await c.get(base, headers=owner)).json()["data"]
    http = {"name": "drain", "description": "d", "access": "read", "method": "GET", "url": "https://core.example/x"}
    for method, path, body in (
        ("PATCH", base, {"description": "changed by Lending"}),
        ("DELETE", base, None),
        ("POST", f"{base}/operations", http),
        ("PATCH", f"{base}/operations/{op}", {"description": "changed by Lending"}),
        ("PUT", f"{base}/connection", {"connectionId": None}),
        ("POST", f"{base}/versions", {"note": "Lending's release"}),
        ("DELETE", f"{base}/pending-changes", None),
        ("POST", f"{base}/reviews", {"note": "Lending asks"}),
        ("POST", f"{base}/approvals/revoke", {"ids": [grant], "reason": "Lending ends it"}),
        ("POST", f"{base}/approvals/{grant}/decide", {"decision": "rejected"}),
        ("POST", f"{base}/operations/{op}/mocks", {"name": "Lending's answer"}),
        ("PATCH", f"{base}/operations/{op}/mocks/{mock_id}", {"name": "Lending's answer"}),
        ("DELETE", f"{base}/operations/{op}/mocks/{mock_id}", None),
    ):
        r = await c.request(method, path, json=body, headers=lending)
        assert r.status_code == 404, (method, path, r.status_code, r.text)
    bulk = await c.post("/v1/tool-modules/bulk-delete", json={"ids": ["mod_core_banking"]}, headers=lending)
    assert bulk.json()["data"] == {"updated": [], "skipped": [{"id": "mod_core_banking", "reason": "Not found"}]}
    assert (await c.get(base, headers=owner)).json()["data"] == held
    assert (await c.get(f"{base}/operations/{op}/mocks", headers=owner)).json() == get.json()
    assert before["approvals"] == held["approvals"]


async def test_another_services_grant_list_still_offers_every_teams_operations(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    # What an agent may be granted is decided by its run's grants and approval token, not the asking service's team.
    c, who = people
    made = await _made(c, who["builder"], "nf-run-path")
    r = await c.get("/v1/grantable-operations", headers=service_headers(tenant))
    assert r.status_code == 200, r.text
    listed = {o.get("moduleId") or o.get("module_id") for o in r.json()["data"]}
    assert "mod_core_banking" in listed and "mod_payments_hub" in listed, listed
    assert made["status"] != "published" or made["id"] in listed
