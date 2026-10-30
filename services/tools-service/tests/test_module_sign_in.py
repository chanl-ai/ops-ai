"""Whose account a module and an operation may be signed in with (c-558), by failure mode: a module given a connection
whose sign-in it does not support, a module changed to a sign-in its connection does not give, an operation that must
act as a person run on the team's account by a call with nobody behind it, and that rule loosened without review."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.auth import AuthFailed
from ops_tools.store.connections import SHARED
from ops_tools.store.modules import ModuleStore

from . import test_personal_sign_in
from .conftest import Api
from .test_personal_sign_in import TEAM, connection, module, rig
from .test_review_decisions import person

# The people-signed-in app of test_personal_sign_in, as a fixture here.
client = test_personal_sign_in.client
system = test_personal_sign_in.system


async def made(c: httpx.AsyncClient, tenant: str, sign_in: str) -> str:
    r = await c.post(
        "/v1/connections",
        json={"name": f"CRM {sign_in}", "authKind": "oauth2_auth_code", "signIn": sign_in},
        headers=person(tenant, "Priya Shah", {TEAM: "admin"}),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["data"]["id"])


def module_in(connection_id: str, sign_in: str) -> dict[str, Any]:
    return {
        "name": f"crm_{sign_in}",
        "displayName": "CRM",
        "system": "CRM",
        "type": "http",
        "endpoint": "",
        "connectionId": connection_id,
        "signIn": sign_in,
        "http": {
            "name": "crm_read",
            "description": "d",
            "access": "read",
            "method": "GET",
            "url": "https://crm.test/a",
        },
    }


def mismatch(r: httpx.Response) -> bool:
    return r.status_code == 400 and r.json()["error"]["code"] == "sign_in_mismatch"


async def test_a_module_takes_only_a_connection_whose_sign_in_it_supports(
    client: httpx.AsyncClient, tenant: str
) -> None:
    security = person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    await client.post("/v1/egress/hosts", json={"value": "crm.test"}, headers=security)
    team, personal = await made(client, tenant, "team"), await made(client, tenant, "person")
    builder = person(tenant, "James Richardson", {TEAM: "builder"})
    refused = await client.post("/v1/tool-modules", json=module_in(team, "person"), headers=builder)
    assert mismatch(refused), refused.text
    ok = await client.post("/v1/tool-modules", json=module_in(personal, "person"), headers=builder)
    assert ok.status_code == 201 and ok.json()["data"]["signIn"] == "person", ok.text
    mod = ok.json()["data"]["id"]
    moved = await client.put(f"/v1/tool-modules/{mod}/connection", json={"connectionId": team}, headers=builder)
    assert mismatch(moved), moved.text
    changed = await client.patch(f"/v1/tool-modules/{mod}", json={"signIn": "team"}, headers=builder)
    assert mismatch(changed), changed.text


async def test_an_operation_that_needs_a_person_never_takes_the_team_backup(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, "test", {"access_token": "at-team", "expires_in": 3600}, SHARED)
    with pytest.raises(AuthFailed) as e:
        await auth.prepare(module(tenant, conn), "test", tool="crm_update", actor="t", needs_person=True)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "needs_person"
    prepared = await auth.prepare(module(tenant, conn), "test", tool="crm_read", actor="t")
    assert prepared is not None and prepared.headers["Authorization"] == "Bearer at-team"


async def test_turning_needs_person_off_waits_for_security(api: Api, engine: AsyncEngine) -> None:
    """Off lets a run with nobody behind it use the team's account, so Security reviews it; on only tightens."""
    store = ModuleStore(engine)
    m = await store.get_any(api.tenant, "mod_core_banking")
    assert m is not None
    for o in m["operations"]:
        o["needs_person"] = o["name"] == "update_address"
    await store.put(m, expected_revision=m["revision"])
    ops = (await api.call("GET", "/mod_core_banking")).json()["data"]["operations"]
    needs, free = (next(o for o in ops if o["name"] == n) for n in ("update_address", "transfer_funds"))
    assert (needs["needsPerson"], free["needsPerson"]) == (True, False)
    off = await api.call("PATCH", f"/mod_core_banking/operations/{needs['id']}", json={"needsPerson": False})
    assert off.status_code == 200, off.text
    on = await api.call("PATCH", f"/mod_core_banking/operations/{free['id']}", json={"needsPerson": True})
    assert on.status_code == 200, on.text
    changes = {c["operation"]: c["major"] for c in on.json()["data"]["pendingChanges"] if "person" in c["detail"]}
    assert changes == {"update_address": True, "transfer_funds": False}, changes


async def test_the_kinds_say_which_take_each_persons_own_sign_in(client: httpx.AsyncClient, tenant: str) -> None:
    """The console offers only the sign-in settings a kind supports, so the kinds must say; every answer is checked
    against openapi.json, where a field the schema lacks fails the call."""
    r = await client.get("/v1/connection-kinds", headers=person(tenant, "James Richardson", {TEAM: "builder"}))
    assert r.status_code == 200, r.text
    per_person = {k["id"]: k["perPerson"] for k in r.json()["data"]["kinds"]}
    assert per_person["oauth2_auth_code"] is True and per_person["oauth2_client_credentials"] is False, per_person
