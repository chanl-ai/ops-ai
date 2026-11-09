"""Each app card's one state and its credential (GET /v1/apps), worked out once here, by failure mode: an app the
team has not turned on reads as needing a sign-in; a signed-in account whose test failed reads as plain connected; a
person's own sign-in on an app each person signs in to is ignored; and the card names the wrong credential.
Rig: test_app_accounts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint

from .test_app_accounts import (
    ID,
    World,
    admin,
    connected,
    signed,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import PLATFORM, person

APP = f"plugin:{ID}"
JAMES = ("James Richardson", {"team_platform": "builder"})


async def card(w: World, tenant: str, who: dict[str, str] | None = None) -> dict[str, Any]:
    r = await w.client.get("/v1/apps", headers=who or admin(tenant))
    assert r.status_code == 200, r.text
    return next(c for c in r.json()["data"] if c["id"] == APP)


def state(c: dict[str, Any]) -> tuple[str, str | None]:
    return c["appState"], c["appStateReason"]


async def test_an_app_the_team_has_not_turned_on_is_off(world: World, tenant: str) -> None:  # noqa: F811
    c = await card(world, tenant)
    assert state(c) == ("off", None) and c["credential"] is None, c


async def test_turned_off_the_app_and_its_page_read_off_and_turn_on_again_alone(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    off = await world.client.put(f"/v1/apps/{APP}/team", json={"enabled": False}, headers=admin(tenant))
    assert off.status_code == 200 and off.json()["data"]["appState"] == "off", off.text
    page = await world.client.get(f"/v1/apps/{APP}", headers=admin(tenant))
    shown = page.json()["data"]["card"]
    assert (shown["appState"], shown["plugin"]["teamOn"]) == ("off", False), shown
    # Turning it on again keeps its account and sign-in: no settings, no credential and no sign-in asked.
    on = await world.client.put(f"/v1/apps/{APP}/team", json={"enabled": True}, headers=admin(tenant))
    assert on.status_code == 200, on.text
    assert state(await card(world, tenant)) == ("connected", None)


async def test_a_team_account_needs_its_sign_in_then_is_connected(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    before = await card(world, tenant)
    shown = before["credential"]
    assert before["appState"] == "needs_sign_in" and shown["type"] == "own" and shown["id"], before
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    assert state(await card(world, tenant)) == ("connected", None)


async def test_a_signed_in_account_whose_test_failed_says_why(world: World, tenant: str) -> None:  # noqa: F811
    conn = await connected(world, tenant)
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    failed = {"status": "failed", "message": "acme.my.desk.test answered 403.", "at": datetime.now(UTC).isoformat()}
    await world.store.set_token_test(tenant, conn, "", failed)
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


async def test_an_apps_account_shows_its_saved_settings(world: World, tenant: str) -> None:  # noqa: F811
    # The app's Settings edit opens on what is saved, as a call reads it, not on the manifest's defaults.
    conn = await connected(world, tenant)
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    shown = await world.host.account_settings(tenant, conn)
    assert shown == {
        "pluginSettings": {"instance_url": "https://acme.my.desk.test", "api_version": "1"},
        "pluginSecrets": {},
    }, shown


def acting_for(tenant: str, sub: str) -> dict[str, str]:
    """agents-service asking for a person: its own service token, and the acting-for token platform-service signs."""
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant,
        scopes=["tools:view", "connections:view"], team_id="team_platform",
    )  # fmt: skip
    claims = {
        "sub": sub, "email": f"{sub}@bank.example", "name": sub, "tenant_id": tenant, "team_id": "team_platform",
        "kind": "acting_for", "act": {"sub": "service:agents"}, "aud": "tools",
    }  # fmt: skip
    return {"Authorization": f"Bearer {service}", "X-Acting-For": mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}


async def test_a_service_asking_for_a_person_reads_that_persons_own_sign_in(world: World, tenant: str) -> None:  # noqa: F811
    # The Tools page asks through agents-service: on an app each person signs in to, the state is the person's.
    conn = await connected(world, tenant)
    row = await world.store.get(tenant, conn)
    assert row is not None
    await world.store.change(tenant, conn, int(row["revision"]), {"sign_in": "person"}, actor="t", at=datetime.now(UTC))
    await signed(world, tenant, conn, "https://acme.my.desk.test", person_id="usr_james")
    james = await card(world, tenant, acting_for(tenant, "usr_james"))
    maya = await card(world, tenant, acting_for(tenant, "usr_maya"))
    assert (james["appState"], james["signIn"]) == ("connected", "person"), james
    assert maya["appState"] == "needs_sign_in", maya


async def test_with_the_team_account_as_backup_a_persons_card_is_their_own_and_a_services_the_teams(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    # Each person's own account with the team's for runs nobody started: a person's calls never use the team's, so
    # their card (and Mine and the chat picker, which read it) needs their own sign-in; a service asking for nobody
    # reads the team account's.
    conn = await connected(world, tenant)
    row = await world.store.get(tenant, conn)
    assert row is not None
    await world.store.change(
        tenant, conn, int(row["revision"]), {"sign_in": "person_or_team"}, actor="t", at=datetime.now(UTC)
    )
    await signed(world, tenant, conn, "https://acme.my.desk.test")
    assert state(await card(world, tenant)) == ("needs_sign_in", "Connect your own account.")
    await signed(world, tenant, conn, "https://acme.my.desk.test", person_id="usr_james")
    assert (await card(world, tenant, acting_for(tenant, "usr_james")))["appState"] == "connected"
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant,
        scopes=["tools:view", "connections:view"], team_id="team_platform",
    )  # fmt: skip
    assert (await card(world, tenant, {"Authorization": f"Bearer {service}"}))["appState"] == "connected"
