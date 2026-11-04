"""The team's app credentials in one answer (the Credentials page), by failure mode: an app on Ops AI's app
reads as the team's own or the other way round; the accounts signed in through it are not counted; its status
ignores the last Test with my account; an app with no OAuth app of its own (a key) is listed; a secret comes back; and
someone who cannot manage the team's apps reads them. Rig: test_app_accounts."""

from __future__ import annotations

from datetime import UTC, datetime

from .test_app_accounts import (
    ID,
    World,
    admin,
    connected,
    signed,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

SAM = ("Sam Adeyemi", {"team_security": "admin"})


async def credentials(w: World, tenant: str) -> list[dict[str, object]]:
    """The Desk app's rows; the dev seed's own apps of the team are listed beside it."""
    r = await w.client.get("/v1/app-credentials", headers=admin(tenant))
    assert r.status_code == 200, r.text
    return [c for c in r.json()["data"] if c["app"] == f"plugin:{ID}" or c["name"] == "Ledger"]


async def test_the_teams_own_client_lists_its_app_permissions_accounts_and_status(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    [row] = await credentials(world, tenant)
    assert {k: row[k] for k in ("id", "name", "app", "appName", "type", "permissions", "accounts", "status")} == {
        "id": conn,
        "name": "Desk",
        "app": f"plugin:{ID}",
        "appName": "Desk",
        "type": "own",
        "permissions": ["api"],
        "accounts": 0,
        "status": "not_tested",
    }, row
    assert str(row["created"]).startswith(str(datetime.now(UTC).year)), row
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    await signed(world, tenant, conn, "https://acme.my.desk.test", person_id="usr_james")
    assert (await credentials(world, tenant))[0]["accounts"] == 2


async def test_an_app_that_signs_in_with_a_key_has_no_app_credential(world: World, tenant: str) -> None:  # noqa: F811
    made = await world.client.post(
        "/v1/connections", json={"name": "Ledger", "authKind": "api_key"}, headers=admin(tenant)
    )
    assert made.status_code == 201, made.text
    assert await credentials(world, tenant) == []


async def test_the_status_is_the_last_test_with_my_account(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    for status, shown in (("failed", "failing"), ("ok", "working")):
        event = {"action": "credential_checked", "environment": "production", "actor": "Priya Shah"}
        detail = {"status": status, "account": None}
        await world.store.note(tenant, conn, {**event, "at": datetime.now(UTC), "detail": detail})
        assert (await credentials(world, tenant))[0]["status"] == shown


async def test_an_app_on_ops_ais_app_reads_so_and_no_secret_comes_back(world: World, tenant: str) -> None:  # noqa: F811
    sealed = "platform-app-secret-7f3a"
    put = await world.client.put(
        f"/v1/plugins/{ID}/app-secret", json={"clientSecret": sealed}, headers=person(tenant, *SAM)
    )
    assert put.status_code == 200, put.text
    on = await world.client.put(f"/v1/plugins/{ID}/team", json={"enabled": True}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    r = await world.client.get("/v1/app-credentials", headers=admin(tenant))
    assert [c["type"] for c in await credentials(world, tenant)] == ["ops_ai"], r.text
    assert sealed not in r.text and "clientSecret" not in r.text


async def test_someone_who_cannot_manage_the_teams_apps_is_refused(world: World, tenant: str) -> None:  # noqa: F811
    await connected(world, tenant)
    viewer = person(tenant, "Wanjiru Kamau", {"team_platform": "viewer"})
    r = await world.client.get("/v1/app-credentials", headers=viewer)
    assert r.status_code == 403, r.text
