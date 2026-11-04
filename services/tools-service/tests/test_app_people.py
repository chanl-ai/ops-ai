"""The app page's People tab (GET /v1/apps/{id}, `people`), by failure mode: a builder reads another person's own
sign-in; a sign-in the system refused, or one that ended with no way to renew, reads Connected; a sign-in on a second
account is missing or named after the default. Rig: test_app_accounts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from ops_store import isolation

from .test_app_accounts import (
    APP,
    TEAM,
    World,
    admin,
    connected,
    world,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from .test_review_decisions import person

BUILDER = ("James Richardson", {TEAM: "builder"})


async def _signed_in(w: World, tenant: str, account: str, who: str, *, ended: bool = False) -> None:
    now = datetime.now(UTC)
    token: dict[str, Any] = {
        "access_ct": "sealed",
        "scopes": [],
        "rotations": 0,
        "refreshed_at": now,
        "account": f"{who}@desk.example",
        **({"expires_at": now - timedelta(hours=1)} if ended else {}),
    }
    with isolation.scope(tenant, TEAM):
        assert await w.store.put_token(tenant, account, token, expected_rotations=None, person=who)


async def _people(w: World, headers: dict[str, str]) -> list[dict[str, Any]]:
    r = await w.client.get(f"/v1/apps/{APP}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["data"]["people"]


async def test_people_carry_their_state_and_account_and_a_builder_reads_only_their_own(
    world: World,  # noqa: F811
    tenant: str,
) -> None:
    default = await connected(world, tenant)
    await _signed_in(world, tenant, default, "usr_priya")
    await _signed_in(world, tenant, default, "usr_james", ended=True)
    with isolation.scope(tenant, TEAM):
        await world.store.mark_refused(tenant, default, "usr_priya", reason="invalid_grant", at=datetime.now(UTC))

    rows = {p["personId"]: p for p in await _people(world, admin(tenant))}
    assert (rows["usr_priya"]["state"], rows["usr_james"]["state"]) == ("refused", "expired"), rows
    assert rows["usr_james"]["account"] == "usr_james@desk.example" and rows["usr_james"]["accountId"] == default
    assert rows["usr_priya"]["mine"] and not rows["usr_james"]["mine"]
    # One sign-in each: nothing to choose, so neither row is marked as a default.
    assert (rows["usr_priya"]["default"], rows["usr_james"]["default"]) == (None, None), rows

    mine = await _people(world, person(tenant, *BUILDER))
    assert [p["personId"] for p in mine] == ["usr_james"], mine
