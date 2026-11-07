"""A call a person started on an app each person signs in to, with the team account as backup, by failure mode: a
person with no sign-in of their own is quietly served by the team account instead of being asked to connect; once
connected their call still goes out as the team; a run nobody started loses the team account; a team-only app starts
asking people to connect; and a person whose own sign-in was refused or has ended is served by the team instead of
being asked to reconnect. Rig: test_personal_sign_in's connections and tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.auth import AuthFailed
from ops_tools.store.connections import SHARED

from .test_personal_sign_in import JAMES, bearer, connection, module, refusing, rig


async def test_a_person_with_no_own_sign_in_is_asked_to_connect_not_given_the_team_account(
    engine: AsyncEngine, tenant: str
) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    with pytest.raises(AuthFailed) as e:
        await bearer(auth, tenant, conn, JAMES)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "not_connected", e.value.details
    assert str(e.value.details["connectUrl"]).startswith("http"), e.value.details


async def test_once_connected_the_same_call_is_signed_as_the_person(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    await tokens.store_answer(tenant, conn, {"access_token": "at-james", "expires_in": 3600}, JAMES.sub)
    prepared = await auth.prepare(module(tenant, conn), "test", tool="crm_update", actor="t", acting_for=JAMES)
    assert prepared is not None
    assert (prepared.headers["Authorization"], prepared.credential) == ("Bearer at-james", "person")


async def test_a_run_nobody_started_still_uses_the_team_account(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    prepared = await auth.prepare(module(tenant, conn), "test", tool="crm_update", actor="t", acting_for=None)
    assert prepared is not None
    assert (prepared.headers["Authorization"], prepared.credential) == ("Bearer at-team", "team")


async def test_a_team_only_app_signs_a_persons_call_with_the_team_account(engine: AsyncEngine, tenant: str) -> None:
    store, tokens, auth = rig(engine)
    conn = await connection(store, tenant, "team")
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    assert await bearer(auth, tenant, conn, JAMES) == "Bearer at-team"


@pytest.mark.parametrize("ended", ["refused", "expired"])
async def test_a_person_whose_own_sign_in_failed_is_asked_to_reconnect_not_given_the_team_account(
    engine: AsyncEngine, tenant: str, ended: str
) -> None:
    store, tokens, auth = rig(engine, refusing())
    conn = await connection(store, tenant, "person_or_team", backup=True)
    await tokens.store_answer(tenant, conn, {"access_token": "at-team", "expires_in": 3600})
    if ended == "refused":
        # The system refuses the refresh of James's spent sign-in.
        await tokens.store_answer(
            tenant, conn, {"access_token": "at-old", "refresh_token": "rt", "expires_in": 1}, JAMES.sub
        )
    else:
        # James's sign-in ended and holds nothing to renew it with.
        await tokens.store_answer(tenant, conn, {"access_token": "at-old", "expires_in": 1}, JAMES.sub)
    held = await store.token(tenant, conn, JAMES.sub)
    assert held is not None and held["expires_at"] < datetime.now(UTC) + timedelta(seconds=5)
    with pytest.raises(AuthFailed) as e:
        await bearer(auth, tenant, conn, JAMES)
    assert e.value.code == "CONNECTION_NOT_LINKED" and e.value.details["reason"] == "refused", (
        e.value.code,
        e.value.details,
    )
    assert await store.token(tenant, conn, SHARED) is not None
