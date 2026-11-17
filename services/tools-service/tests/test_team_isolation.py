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

from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore

from .conftest import FakeReviews, build_app, opa_client, service_headers
from .test_review_decisions import HOST, PLATFORM, introspect, jwks, person

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


async def test_security_reads_a_module_waiting_on_its_review_and_changes_nothing(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str
) -> None:
    # The workspace's Security team decides module security reviews, so it reads each team's module waiting on one,
    # read-only; another team's admin asking for the same view sees none of it.
    c, who = people
    owner = person(tenant, "Nora Builder", {NEW_TEAM: "admin"})
    assert (await c.post("/v1/egress/hosts", json={"value": HOST}, headers=who["security"])).status_code in (200, 201)
    made = await _made(c, owner, "nf-review")
    op = {"name": "get_x", "description": "d", "access": "read", "method": "GET", "url": f"https://{HOST}/x"}
    assert (await c.post(f"/v1/tool-modules/{made['id']}/operations", json=op, headers=owner)).status_code == 200
    asked = await c.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "first"}, headers=owner)
    assert asked.status_code == 200, asked.text
    view = {"view": "security_review", "pageSize": 100}
    for whom, seen in ((who["security"], True), (who["outsider"], False), (who["lending"], False)):
        got = await c.get(f"/v1/tool-modules/{made['id']}", headers=whom)
        assert got.status_code == (200 if seen else 404), got.text
        assert (made["id"] in _ids(await c.get("/v1/tool-modules", params=view, headers=whom))) is seen, whom
    for method, path, body in (
        ("PATCH", f"/v1/tool-modules/{made['id']}", {"description": "changed by Security"}),
        ("DELETE", f"/v1/tool-modules/{made['id']}", None),
        ("POST", f"/v1/tool-modules/{made['id']}/operations", op),
    ):
        r = await c.request(method, path, json=body, headers=who["security"])
        assert r.status_code == 404, (method, path, r.status_code, r.text)


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


def _signed(tenant: str, name: str, access: dict[str, list[str]], team: str) -> dict[str, str]:
    """A token as platform-service mints one from role assignments (the `access` claim), acting in `team`."""
    first = name.split(maxsplit=1)[0].lower()
    claims = {
        "sub": f"usr_{first}",
        "email": f"{first}@bank.example",
        "name": name,
        "kind": "person",
        "security_team": "team_security",
        "aud": ["tools"],
        "tenant_id": tenant,
        "team_ids": [t for t in access if t != "*"],
        "access": access,
        "auth_method": "session",
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": team}


# Lending holds only its workflow's grant on Core Banking (the all-scope Platform team's, as team_ops is). Every
# write, test and run from the module screens answers as for a module the caller cannot see, and the module's
# buttons are off: the grant lets Lending's workflows call the operation through the gateway, nothing more. A
# workspace admin (Admin in every team) acting in Lending is held to Lending's view too.
GRANTEE_CALLERS = {
    "builder of the grantee team": ({"team_lending": ["builder"]}, "team_lending"),
    "admin of the grantee team": ({"team_lending": ["admin"]}, "team_lending"),
    "workspace admin acting in the grantee team": ({"team_lending": ["viewer"], "*": ["admin"]}, "team_lending"),
}


@pytest.mark.parametrize("caller", list(GRANTEE_CALLERS))
async def test_a_team_holding_only_a_workflow_grant_changes_nothing_of_the_module(
    people: tuple[httpx.AsyncClient, dict[str, dict[str, str]]], tenant: str, caller: str
) -> None:
    c, _ = people
    owner = person(tenant, "Pat Platform", {"team_platform": "admin"})
    access, team = GRANTEE_CALLERS[caller]
    grantee = _signed(tenant, "Lena Lending", access, team)
    base = "/v1/tool-modules/mod_core_banking"
    before = (await c.get(base, headers=owner)).json()["data"]
    op, name = before["operations"][0]["id"], before["operations"][0]["name"]
    grant = next(a["id"] for a in before["approvals"] if a["status"] == "approved")
    mock = await c.post(f"{base}/operations/{op}/mocks", json={"name": "Owner's answer"}, headers=owner)
    assert mock.status_code == 201, mock.text
    mock_id = mock.json()["data"]["id"]
    get = await c.get(f"{base}/operations/{op}/mocks", headers=owner)
    held = (await c.get(base, headers=owner)).json()["data"]
    http = {"name": "drain", "description": "d", "access": "read", "method": "GET", "url": "https://core.example/x"}
    tries: tuple[tuple[str, str, object], ...] = (
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
        # Trying a tool is the authoring page's; a grant team calls it through the gateway's /v1/calls.
        ("POST", f"{base}/test", {"operation": name, "contextId": "owner", "target": "stub", "input": {}}),
        ("POST", f"{base}/operations/{name}/run", {"mode": "mock", "input": {}}),
    )
    table: dict[str, object] = {}
    for method, path, body in tries:
        r = await c.request(method, path, json=body, headers=grantee)
        table[f"{method} {path.removeprefix(base) or '/'}"] = r.status_code
    bulk = await c.post("/v1/tool-modules/bulk-delete", json={"ids": ["mod_core_banking"]}, headers=grantee)
    table["POST bulk-delete"] = bulk.json()["data"]
    seen = await c.get(base, headers=grantee)
    assert seen.status_code == 200, seen.text
    table.update({k: seen.json()["data"][k] for k in ("canEdit", "canDelete", "canPublish")})
    # The list row follows the detail's flag, and the owning team's row still offers the edit.
    for who, h in (("list canEdit", grantee), ("owner's list canEdit", owner)):
        rows = (await c.get("/v1/tool-modules", params={"ids": "mod_core_banking"}, headers=h)).json()["data"]["data"]
        table[who] = [r["canEdit"] for r in rows]
    assert table == {
        **{f"{m} {p.removeprefix(base) or '/'}": 404 for m, p, _ in tries},
        "POST bulk-delete": {"updated": [], "skipped": [{"id": "mod_core_banking", "reason": "Not found"}]},
        "canEdit": False,
        "canDelete": False,
        "canPublish": False,
        "list canEdit": [False],
        "owner's list canEdit": [True],
    }, caller
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


@pytest.fixture
async def gateway(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[httpx.AsyncClient]:
    """`people`'s app with the gateway's policy engine, so a call is decided and logged as in a run."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    async with opa_client() as opa:
        app = build_app(engine, seed, tenant, auth=auth, opa=opa)
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c,
        ):
            yield c


async def _teamless_call(c: httpx.AsyncClient, tenant: str, key: str, team: str | None = None) -> str:
    """A call refused on a tool no module holds, from a service token naming `team`: with none, logged with no team."""
    body = {"tool": "drop_tables", "input": {}, "key": key, "runContext": {"act": "test"}}
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"], team_id=team
    )
    r = await c.post("/v1/calls", json=body, headers={"Authorization": f"Bearer {token}"})
    call_id = r.json().get("callId") or r.json().get("error", {}).get("details", {}).get("callId")
    assert r.status_code == 403 and call_id, r.text
    return str(call_id)


async def _page(c: httpx.AsyncClient, who: dict[str, str]) -> dict[str, Any]:
    r = await c.get("/v1/executions", params={"pageSize": 100}, headers=who)
    assert r.status_code == 200, r.text
    return r.json()["data"]


# Who reads a call that named no team (a refusal is audit evidence): whoever holds activity.view in every team, the
# account's reader, as platform-service reads the account's own audit entries; a team's own reader does not.
TEAMLESS_READERS = {
    "workspace admin (Admin in every team)": ({"team_platform": ["viewer"], "*": ["admin"]}, True),
    "admin of the acting team only": ({"team_platform": ["admin"]}, False),
    "builder of the acting team only": ({"team_platform": ["builder"]}, False),
}


@pytest.mark.parametrize("caller", list(TEAMLESS_READERS))
async def test_a_call_that_named_no_team_is_read_by_the_every_team_reader_only(
    gateway: httpx.AsyncClient,
    tenant: str,
    caller: str,
) -> None:
    client = gateway
    access, sees = TEAMLESS_READERS[caller]
    who = _signed(tenant, "Wanda Reader", access, "team_platform")
    before = await _page(client, who)
    mine = await _teamless_call(client, tenant, f"teamless-{caller}")
    other = await _teamless_call(client, f"{tenant}_other", f"teamless-other-{caller}")
    cards = await _teamless_call(client, tenant, f"teamless-cards-{caller}", team="team_cards")
    page = await _page(client, who)
    ids = {row["id"] for row in page["data"]}
    assert (mine in ids, other in ids, cards in ids) == (sees, False, False), (caller, ids)
    assert page["pagination"]["total"] == before["pagination"]["total"] + int(sees) == len(page["data"])
    refused = page["facets"]["result"].get("Refused", 0)
    assert refused == before["facets"]["result"].get("Refused", 0) + int(sees), page["facets"]
    assert (await client.get(f"/v1/executions/{mine}", headers=who)).status_code == (200 if sees else 404)
    for hidden in (other, cards):
        assert (await client.get(f"/v1/executions/{hidden}", headers=who)).status_code == 404
