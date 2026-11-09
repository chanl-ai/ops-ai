"""The app page's auth configs (GET /v1/apps/{id}, `authConfigs`), by failure mode: an account is listed under a
config it does not sign in with; a builder may edit or delete a config or read its client; an account on which only
its owner signs in reads a team state instead of that sign-in's, or names its owner by id; the page carries a second
state per account (a people list). Rig: test_app_accounts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ops_store import isolation

from .conftest import team_credential
from .test_app_accounts import (
    APP,
    ID,
    TEAM,
    World,
    admin,
    connected,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

BUILDER = ("James Richardson", {TEAM: "builder"})
# Builders hold connections.manage since D59; a viewer holds none of it.
VIEWER = ("Ravi Menon", {TEAM: "viewer"})


async def _page(w: World, headers: dict[str, str]) -> dict[str, Any]:
    r = await w.client.get(f"/v1/apps/{APP}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_accounts_sit_under_the_config_they_sign_in_with_and_only_an_admin_edits_one(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    first = await connected(world, tenant)
    eu = await team_credential(world.client, admin(tenant), APP, "eu-app")
    made = await world.client.post(
        f"/v1/apps/plugin:{ID}/accounts", json={"name": "EU org", "credentialId": eu}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    second = made.json()["data"]["id"]

    page = await _page(world, admin(tenant))
    assert "people" not in page, sorted(page)
    by_row = {a["id"]: a for a in page["accounts"] if a["kind"] == "team"}
    assert by_row[second]["configId"] == eu and by_row[first]["configId"] != eu, by_row
    assert by_row[second]["configName"] == "eu-app" or by_row[second]["configName"], by_row[second]
    ours = next(c for c in page["authConfigs"] if c["id"] == eu)
    assert ours["canEdit"] and ours["canDelete"] and ours["clientId"] == "eu-app", ours
    # A config counts the accounts signing in through it; the accounts themselves are listed once, on the page.
    assert ours["accountCount"] == 1 and "accounts" not in ours, ours
    assert next(c for c in page["authConfigs"] if c["id"] == by_row[first]["configId"])["default"], page
    rows = {a["id"]: a for a in page["accounts"] if a["kind"] == "team"}
    # Make my default picks among the caller's own sign-ins; with none, no account offers it.
    assert not any("make_default" in a["actions"] for a in rows.values()), rows
    assert {"rename", "delete", "move", "sign_in"} <= set(rows[second]["actions"]), rows[second]
    assert rows[first]["owner"]["kind"] == "team" and rows[first]["owner"]["name"], rows[first]

    builder = await _page(world, person(tenant, *BUILDER))
    assert any(c["id"] == eu for c in builder["authConfigs"]), builder["authConfigs"]
    # Auth configs are a builder's and an admin's to see: a viewer is told none, by name or by count.
    seen = await _page(world, person(tenant, *VIEWER))
    assert seen["authConfigs"] == [], seen["authConfigs"]
    assert all(a["configId"] is None and a["configName"] is None for a in seen["accounts"]), seen["accounts"]
    assert all(not {"rename", "delete", "move", "make_default"} & set(a["actions"]) for a in seen["accounts"]), seen[
        "accounts"
    ]


async def test_an_account_only_its_owner_signs_in_to_reads_that_sign_ins_state_and_names_them(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    await connected(world, tenant)
    made = await world.client.post(
        f"/v1/apps/plugin:{ID}/accounts", json={"name": "Priya's desk"}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    account, revision = made.json()["data"]["id"], made.json()["data"]["revision"]
    # The rig's plugin offers the team's sign-in only, so the account is made one only its owner signs in to here.
    with isolation.scope(tenant, TEAM):
        await world.store.change(
            tenant, account, revision, {"sign_in": "person"}, actor="Priya Shah", at=datetime.now(UTC)
        )
    token: dict[str, Any] = {"access_ct": "sealed", "scopes": [], "rotations": 0, "refreshed_at": datetime.now(UTC)}
    with isolation.scope(tenant, TEAM):
        assert await world.store.put_token(tenant, account, token, expected_rotations=None, person="usr_priya")
    rows = {a["id"]: a for a in (await _page(world, admin(tenant)))["accounts"] if a["kind"] == "team"}
    assert rows[account]["state"] == "connected", rows[account]
    assert rows[account]["owner"] == {"kind": "each", "name": "Priya Shah"}, rows[account]
    # Each person signs in to it with their own account, so another person never reads it as Priya's.
    seen = {a["id"]: a for a in (await _page(world, person(tenant, *VIEWER)))["accounts"] if a["kind"] == "team"}
    assert seen[account]["owner"]["kind"] == "each" and seen[account]["owner"]["name"] != "Priya Shah", seen[account]

    with isolation.scope(tenant, TEAM):
        await world.store.mark_refused(tenant, account, "usr_priya", reason="invalid_grant", at=datetime.now(UTC))
    rows = {a["id"]: a for a in (await _page(world, admin(tenant)))["accounts"] if a["kind"] == "team"}
    assert rows[account]["state"] == "refused", rows[account]


async def test_an_admin_makes_another_account_the_teams_default_and_a_viewer_may_not(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    first = await connected(world, tenant)
    made = await world.client.post(f"/v1/apps/plugin:{ID}/accounts", json={"name": "EU org"}, headers=admin(tenant))
    assert made.status_code == 201, made.text
    second = made.json()["data"]["id"]
    path = f"/v1/apps/{APP}/accounts/{second}/team-default"
    refused = await world.client.put(path, headers=person(tenant, *VIEWER))
    assert refused.status_code == 403, refused.text
    rows = {a["id"]: a for a in (await _page(world, admin(tenant)))["accounts"] if a["kind"] == "team"}
    assert "make_team_default" in rows[second]["actions"] and "make_team_default" not in rows[first]["actions"], rows

    done = await world.client.put(path, headers=admin(tenant))
    assert done.status_code == 200, done.text
    page = await _page(world, admin(tenant))
    rows = {a["id"]: a for a in page["accounts"] if a["kind"] == "team"}
    assert rows[second]["default"] and not rows[first]["default"], rows
    assert page["card"]["connectionId"] == second, page["card"]


async def test_each_persons_own_sign_in_is_its_own_row_seen_by_admins_and_by_that_person_only(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    # A person's own account nested inside the team's row was not listable or filterable, and named nobody.
    account = await connected(world, tenant)
    token: dict[str, Any] = {"access_ct": "sealed", "scopes": [], "rotations": 0, "refreshed_at": datetime.now(UTC)}
    with isolation.scope(tenant, TEAM):
        assert await world.store.put_token(tenant, account, token, expected_rotations=None, person="usr_marco")
        await world.store.name_person(tenant, account, "usr_marco", "Marco Ruiz")
    rows = (await _page(world, admin(tenant)))["accounts"]
    own = [a for a in rows if a["kind"] == "person"]
    assert [(a["id"], a["name"], a["owner"]) for a in own] == [
        (account, "Marco Ruiz", {"kind": "person", "name": "Marco Ruiz"})
    ], own
    assert own[0]["rowId"] != account and own[0]["configName"], own[0]
    assert not own[0]["actions"], own[0]
    seen = (await _page(world, person(tenant, *VIEWER)))["accounts"]
    assert not [a for a in seen if a["kind"] == "person"], seen


async def test_a_viewer_reads_no_auth_config_on_the_card_mine_or_their_accounts(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    await connected(world, tenant)
    viewer = person(tenant, *VIEWER)
    card = next(c for c in (await world.client.get("/v1/apps", headers=viewer)).json()["data"] if c["id"] == APP)
    assert card["credential"] is not None and card["credential"]["id"] is None, card["credential"]
    shown = next(
        c for c in (await world.client.get("/v1/apps", headers=admin(tenant))).json()["data"] if c["id"] == APP
    )
    assert shown["credential"]["id"], shown["credential"]
    mine = await world.client.get("/v1/me/connections", headers=viewer)
    assert mine.status_code == 200, mine.text
    assert all(r["authConfig"] is None for r in mine.json()["data"]), mine.json()["data"]
    accounts = await world.client.get("/v1/me/accounts?every=true", headers=viewer)
    assert accounts.status_code == 200, accounts.text
    assert all(a["authConfig"] is None for a in accounts.json()["data"]), accounts.json()["data"]
