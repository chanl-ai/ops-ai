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
    held = {c["id"]: [a["id"] for a in c["accounts"]] for c in page["authConfigs"]}
    assert held[eu] == [second] and first in next(v for k, v in held.items() if k != eu and v), held
    ours = next(c for c in page["authConfigs"] if c["id"] == eu)
    assert ours["canEdit"] and ours["canDelete"] and ours["clientId"] == "eu-app", ours
    assert next(c for c in page["authConfigs"] if first in [a["id"] for a in c["accounts"]])["default"], page
    rows = {a["id"]: a for c in page["authConfigs"] for a in c["accounts"]}
    # Make my default picks among the caller's own sign-ins; with none, no account offers it.
    assert not any("make_default" in a["actions"] for a in rows.values()), rows
    assert {"rename", "delete", "move", "sign_in"} <= set(rows[second]["actions"]), rows[second]
    assert rows[first]["owner"]["kind"] == "team" and rows[first]["owner"]["name"], rows[first]

    seen = await _page(world, person(tenant, *VIEWER))
    mine = next(c for c in seen["authConfigs"] if c["id"] == eu)
    assert not mine["canEdit"] and not mine["canDelete"] and mine["clientId"] is None, mine
    assert all(
        not {"rename", "delete", "move", "make_default"} & set(a["actions"])
        for c in seen["authConfigs"]
        for a in c["accounts"]
    ), seen["authConfigs"]


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
    rows = {a["id"]: a for c in (await _page(world, admin(tenant)))["authConfigs"] for a in c["accounts"]}
    assert rows[account]["state"] == "connected", rows[account]
    assert rows[account]["owner"] == {"kind": "each", "name": "Priya Shah"}, rows[account]
    # Each person signs in to it with their own account, so another person never reads it as Priya's.
    seen = {a["id"]: a for c in (await _page(world, person(tenant, *VIEWER)))["authConfigs"] for a in c["accounts"]}
    assert seen[account]["owner"]["kind"] == "each" and seen[account]["owner"]["name"] != "Priya Shah", seen[account]

    with isolation.scope(tenant, TEAM):
        await world.store.mark_refused(tenant, account, "usr_priya", reason="invalid_grant", at=datetime.now(UTC))
    rows = {a["id"]: a for c in (await _page(world, admin(tenant)))["authConfigs"] for a in c["accounts"]}
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
    rows = {a["id"]: a for c in (await _page(world, admin(tenant)))["authConfigs"] for a in c["accounts"]}
    assert "make_team_default" in rows[second]["actions"] and "make_team_default" not in rows[first]["actions"], rows

    done = await world.client.put(path, headers=admin(tenant))
    assert done.status_code == 200, done.text
    page = await _page(world, admin(tenant))
    rows = {a["id"]: a for c in page["authConfigs"] for a in c["accounts"]}
    assert rows[second]["default"] and not rows[first]["default"], rows
    assert page["card"]["connectionId"] == second, page["card"]
