"""Each app card's one state and its credential (GET /v1/systems), worked out once here, by failure mode: an app the
team has not turned on reads as needing a sign-in; a signed-in account whose test failed reads as plain connected; a
person's own sign-in on an app each person signs in to is ignored; and the card names the wrong credential.
Rig: test_app_accounts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .test_app_accounts import (
    ID,
    World,
    admin,
    connected,
    signed,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

APP = f"plugin:{ID}"
JAMES = ("James Richardson", {"team_platform": "builder"})


async def card(w: World, tenant: str, who: dict[str, str] | None = None) -> dict[str, Any]:
    r = await w.client.get("/v1/systems", headers=who or admin(tenant))
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["data"] if c["id"] == APP)


def state(c: dict[str, Any]) -> tuple[str, str | None]:
    return c["appState"], c["appStateReason"]


async def test_an_app_the_team_has_not_turned_on_is_not_installed(world: World, tenant: str) -> None:  # noqa: F811
    c = await card(world, tenant)
    assert state(c) == ("not_installed", None) and c["credential"] is None, c


async def test_a_team_account_needs_its_sign_in_then_is_connected(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    before = await card(world, tenant)
    assert before["appState"] == "needs_sign_in" and before["credential"] == {"name": "Desk", "type": "own"}, before
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    assert state(await card(world, tenant)) == ("connected", None)


async def test_a_signed_in_account_whose_test_failed_says_why(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    failed = {"status": "failed", "message": "acme.my.desk.test answered 403.", "at": datetime.now(UTC).isoformat()}
    await world.store.set_token_test(tenant, conn, "production", "", failed)
    assert state(await card(world, tenant)) == ("test_failed", "acme.my.desk.test answered 403.")


async def test_on_an_app_each_person_signs_in_to_the_card_is_the_callers_own(world: World, tenant: str) -> None:  # noqa: F811
    # The test plugin offers the team account only; its connection is set to each person's own sign-in here.
    conn = await connected(world, tenant)
    row = await world.store.get(tenant, conn)
    assert row is not None
    await world.store.change(tenant, conn, int(row["revision"]), {"sign_in": "person"}, actor="t", at=datetime.now(UTC))
    await signed(world, tenant, conn, "https://acme.my.desk.test", person_id="usr_james")
    james = person(tenant, *JAMES)
    assert (await card(world, tenant, james))["appState"] == "connected"
    assert (await card(world, tenant))["appState"] == "needs_sign_in"


async def test_an_apps_account_shows_its_saved_settings_per_environment(world: World, tenant: str) -> None:  # noqa: F811
    # The app's Settings edit opens on what is saved, as a call reads it, not on the manifest's defaults.
    conn = await connected(world, tenant)
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    shown = await world.host.environment_settings(tenant, conn, ["production", "test"])
    assert shown["production"] == {
        "pluginSettings": {"instance_url": "https://acme.my.desk.test", "api_version": "1"},
        "pluginSecrets": {},
    }, shown
    assert shown["test"]["pluginSettings"] == {"api_version": "1"}, shown
