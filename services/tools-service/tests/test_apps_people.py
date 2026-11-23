"""Apps > People and End sign-in, by failure mode: someone who may not manage the team's apps reads every person's
sign-ins, or is told "people" is not an app; the list counts a person's sign-ins in the wrong state or pages people
apart; an admin's End leaves the person's next call signed, their My apps card silent about who ended it, no audit
row, or a second row on a second End; and a call never marks when the sign-in was last used, or writes it on every
call. Rig: test_personal_sign_in's connections, tokens and HTTP client."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ActingForPerson
from ops_tools.auth import AuthFailed
from ops_tools.store.connections import ConnectionStore, NewAccount

from .test_personal_sign_in import (
    JAMES,
    SETTINGS,
    TEAM,
    bearer,
    client,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    connection,
    rig,
    system,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

DANA = ActingForPerson(sub="usr_dana", email="dana@bank.example", name="Dana", team_id=TEAM)


def admin(tenant: str) -> dict[str, str]:
    return person(tenant, "Priya Shah", {TEAM: "admin"})


async def other_app(store: ConnectionStore, tenant: str) -> str:
    """A second app each person signs in to, so a person's counts span two apps."""
    now = datetime.now(UTC)
    row: NewAccount = {
        "tenant_id": tenant,
        "id": "con_ledger",
        "app_id": "con_ledger",
        "team_id": TEAM,
        "name": "Ledger",
        "auth_kind": "oauth2_auth_code",
        "sign_in": "person",
        "team_backup": False,
        "status": "healthy",
        "revision": 1,
        "created_by": "t",
        "created_at": now,
        "updated_by": "t",
        "updated_at": now,
    }
    assert await store.create(row, actor="t", at=now)
    await store.change(tenant, "con_ledger", 1, {"settings": {**SETTINGS}, "secrets": {}}, actor="t", at=now)
    return "con_ledger"


@pytest.mark.parametrize("role", ["chat_user", "builder"])
async def test_people_and_end_sign_in_are_refused_naming_manage_apps(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
    role: str,
) -> None:
    store, tokens, _ = rig(engine)
    conn = await connection(store, tenant, "person")
    await tokens.store_answer(tenant, conn, {"access_token": "at-dana", "expires_in": 3600}, DANA.sub)
    who = person(tenant, "James Richardson", {TEAM: role})
    listed = await client.get("/v1/apps/people", headers=who)
    assert listed.status_code == 403, listed.text
    assert {"area": "connections", "action": "manage"}.items() <= listed.json()["error"]["details"].items(), listed.text
    ended = await client.post(f"/v1/apps/{conn}/accounts/{conn}/people/{DANA.sub}/sign-out", headers=who)
    assert ended.status_code == 403, ended.text
    assert (await store.token(tenant, conn, DANA.sub)).refused_at is None  # type: ignore[union-attr]


async def test_people_lists_each_persons_sign_ins_counted_by_state_and_filtered(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    store, tokens, _ = rig(engine)
    crm = await connection(store, tenant, "person")
    ledger = await other_app(store, tenant)
    await tokens.store_answer(tenant, crm, {"access_token": "at-d", "expires_in": 3600}, DANA.sub)
    await tokens.store_answer(tenant, ledger, {"access_token": "at-d2", "expires_in": 3600}, DANA.sub)
    await store.mark_refused(tenant, ledger, DANA.sub, reason="invalid_grant", at=datetime.now(UTC))
    # James's sign-in ended an hour ago and holds no refresh token: expired.
    await tokens.store_answer(tenant, crm, {"access_token": "at-j", "expires_in": -3600}, JAMES.sub)
    await store.name_person(tenant, crm, DANA.sub, "Dana Whitfield")
    await store.name_person(tenant, crm, JAMES.sub, "James Richardson")

    r = await client.get("/v1/apps/people", headers=admin(tenant))
    assert r.status_code == 200, r.text
    page = r.json()["data"]
    rows = {p["name"]: p for p in page["data"]}
    assert [p["name"] for p in page["data"]] == ["Dana Whitfield", "James Richardson"]
    assert page["pagination"]["total"] == 2
    dana, james = rows["Dana Whitfield"], rows["James Richardson"]
    assert (dana["connected"], dana["expired"], dana["refused"]) == (1, 0, 1), dana
    assert (james["connected"], james["expired"], james["refused"]) == (0, 1, 0), james
    assert sorted(a["appId"] for a in dana["apps"]) == sorted([crm, ledger])
    assert {s["appId"]: s["state"] for s in dana["signIns"]} == {crm: "connected", ledger: "refused"}
    assert page["facets"]["state"] == {"connected": 1, "refused": 1, "expired": 1}, page["facets"]

    refused = await client.get("/v1/apps/people", params={"state": "refused"}, headers=admin(tenant))
    assert [p["name"] for p in refused.json()["data"]["data"]] == ["Dana Whitfield"]
    searched = await client.get("/v1/apps/people", params={"search": "jam", "pageSize": 1}, headers=admin(tenant))
    assert [p["name"] for p in searched.json()["data"]["data"]] == ["James Richardson"]


async def test_an_admin_ends_a_persons_sign_in_once_and_their_next_call_asks_them_to_connect(
    client: httpx.AsyncClient,  # noqa: F811
    engine: AsyncEngine,
    tenant: str,
) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    # A team account is connected too: ending Dana's own must not leave her calls on it.
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    await tokens.store_answer(tenant, conn, {"access_token": "at-dana", "expires_in": 3600}, DANA.sub)
    assert await bearer(auth, tenant, conn, DANA) == "Bearer at-dana"

    url = f"/v1/apps/{conn}/accounts/{conn}/people/{DANA.sub}/sign-out"
    first = await client.post(url, headers=admin(tenant))
    assert first.status_code == 200, first.text
    assert {"refusedReason": "ended_by_admin", "changed": True}.items() <= first.json()["data"].items(), first.text
    with pytest.raises(AuthFailed) as e:
        await bearer(auth, tenant, conn, DANA)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "refused", e.value.details

    again = await client.post(url, headers=admin(tenant))
    assert again.status_code == 200 and again.json()["data"]["changed"] is False, again.text
    ended = [a for a in await store.audit(tenant, conn) if a.action == "sign_in_ended"]
    assert len(ended) == 1 and ended[0].detail == {"person": DANA.sub}, ended

    mine = await client.get("/v1/me/connections", headers=person(tenant, "Dana Whitfield", {TEAM: "viewer"}))
    assert mine.status_code == 200, mine.text
    card = next(c for c in mine.json()["data"] if c["appId"] == conn)
    assert card["appStateReason"] == "Ended by an admin", card
    gone = await client.post(f"/v1/apps/{conn}/accounts/{conn}/people/usr_nobody/sign-out", headers=admin(tenant))
    assert gone.status_code == 404, gone.text


async def test_a_call_marks_its_sign_in_last_used_at_most_once_a_minute(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person")
    await tokens.store_answer(tenant, conn, {"access_token": "at-james", "expires_in": 3600}, JAMES.sub)
    before = datetime.now(UTC)
    await bearer(auth, tenant, conn, JAMES)
    first = (await store.token(tenant, conn, JAMES.sub)).last_used_at  # type: ignore[union-attr]
    assert first is not None and before - timedelta(seconds=1) <= first <= datetime.now(UTC), first
    await bearer(auth, tenant, conn, JAMES)
    assert (await store.token(tenant, conn, JAMES.sub)).last_used_at == first  # type: ignore[union-attr]
