"""A run waiting for a person's own account goes on once they connect, tools-service's half, by failure
mode: the refusal does not say which event and key mean "this person connected", so a run cannot wait for it; and a
person who connects, by an OAuth sign-in or by giving their key, reports nothing, so a waiting run never wakes. The
event's key is the one the refusal named, so the run wakes for its person only."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.auth import AuthFailed
from ops_tools.store.modules import service_outbox

from . import test_person_credentials as keys
from . import test_personal_sign_in as oauth
from .test_personal_sign_in import client, system  # noqa: F401  # pyright: ignore[reportUnusedImport]

CONNECTED = "app_account.connected"


async def connected(engine: AsyncEngine, tenant: str) -> list[dict[str, Any]]:
    o = service_outbox.c
    async with engine.connect() as c:
        rows = await c.execute(sa.select(service_outbox).where(o.tenant_id == tenant, o.name == CONNECTED))
        return [dict(r) for r in rows.mappings()]


async def test_a_person_without_their_account_is_told_the_event_that_means_they_connected(
    engine: AsyncEngine, tenant: str
) -> None:
    store, _, auth = keys._rig(engine)  # pyright: ignore[reportPrivateUsage]
    conn = await keys._connection(store, tenant, "basic")  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(AuthFailed) as e:
        await keys._call(auth, tenant, conn, keys.JAMES)  # pyright: ignore[reportPrivateUsage]
    assert e.value.details["connectedEvent"] == {"name": CONNECTED, "key": f"{conn}:{keys.JAMES.sub}"}
    assert e.value.details["teamAccount"] is False, "a connection each person signs in to has no team account"


async def test_giving_your_key_reports_that_you_connected_under_the_refusals_key(
    engine: AsyncEngine,
    tenant: str,
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    conn = await keys._ledger(client, tenant)  # pyright: ignore[reportPrivateUsage]
    given = await keys._give(client, tenant, conn, keys.JAMES_P, key="key-james")  # pyright: ignore[reportPrivateUsage]
    assert given.status_code == 200, given.text
    [event] = await connected(engine, tenant)
    assert (event["event_key"], event["team_id"]) == (f"{conn}:{keys.JAMES.sub}", keys.TEAM), event
    assert event["payload"] == {"connectionId": conn, "app": "Ledger"}, event
    assert "key-james" not in str(event)


async def test_an_oauth_sign_in_of_your_own_reports_that_you_connected(
    engine: AsyncEngine,
    tenant: str,
    client: httpx.AsyncClient,  # noqa: F811
) -> None:
    conn = await oauth.personal_connection(client, tenant)
    await oauth.sign_in(client, tenant, conn, oauth.JAMES_P, "james")
    assert [e["event_key"] for e in await connected(engine, tenant)] == [f"{conn}:usr_james"]


async def test_a_connection_the_team_backs_says_its_team_account_may_stand_in(engine: AsyncEngine, tenant: str) -> None:
    store, _, auth = oauth.rig(engine)
    conn = await oauth.connection(store, tenant, "person_or_team", backup=True)
    with pytest.raises(AuthFailed) as e:
        await oauth.bearer(auth, tenant, conn, oauth.JAMES)
    assert e.value.details["teamAccount"] is True, e.value.details
