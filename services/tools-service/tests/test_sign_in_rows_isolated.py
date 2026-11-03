"""A person's saved sign-ins are held to their connection's team by the database, by failure mode: another team
reads them through the store; another team reads or changes them with SQL that names no team, which only the
database policy can stop; a new row lands without its connection's team; a connection moved to another team leaves
its rows behind. Runs on the compose PostgreSQL as `ops_tools_tenant`, the role every store transaction runs as, since
the database user the tests connect as bypasses row security."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_tools.store.connections import (
    ConnectionStore,
    connect_links,
    connection_environments,
    connection_tokens,
    oauth_states,
)

ROLE = "ops_tools_tenant"
TEAM_A, TEAM_B = "team_cards", "team_ops"
PERSON = "usr_maya"
SIGN_IN_TABLES = (connection_tokens, oauth_states, connection_environments, connect_links)


async def _signed_in(engine: AsyncEngine, tenant: str, team: str = TEAM_A) -> tuple[ConnectionStore, str]:
    """A team's connection holding a person's token, a sign-in in progress, a test environment and a connect link."""
    store, now = ConnectionStore(engine), datetime.now(UTC)
    con = f"con_{team}"
    row = {
        "tenant_id": tenant,
        "id": con,
        "team_id": team,
        "name": "CRM",
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
    with isolation.scope(tenant, team):
        assert await store.create(row, actor="t", at=now)
        await store.change(tenant, con, 1, {}, actor="t", at=now, environment=("test", {"baseUrl": "https://x"}, {}))
        token: dict[str, Any] = {"access_ct": "sealed", "scopes": [], "rotations": 0, "refreshed_at": now}
        assert await store.put_token(tenant, con, "test", token, expected_rotations=None, person=PERSON)
        await store.add_state(
            {
                "tenant_id": tenant,
                "state_hash": f"s_{team}",
                "connection_id": con,
                "environment": "test",
                "person_id": PERSON,
                "verifier_ct": "sealed",
                "redirect_uri": "https://console.bank.test/back",
                "expires_at": now + timedelta(minutes=10),
            },
            now=now,
        )
        await store.add_link(
            {
                "tenant_id": tenant,
                "token_hash": f"l_{team}",
                "connection_id": con,
                "environment": "test",
                "team_id": team,
                "person_id": PERSON,
                "email": "maya@bank.test",
                "scopes": "",
                "reason": "not_connected",
                "created_at": now,
                "expires_at": now + timedelta(days=1),
            },
            now=now,
        )
    return store, con


async def test_another_team_finds_no_sign_in_through_the_store(engine: AsyncEngine, tenant: str) -> None:
    store, con = await _signed_in(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        assert await store.token(tenant, con, "test", PERSON) is None
        assert await store.tokens(tenant, con) == []
        assert await store.people(tenant, con) == []
        assert await store.link(tenant, f"l_{TEAM_A}") is None
        now = datetime.now(UTC)
        assert await store.take_state(tenant, f"s_{TEAM_A}", connection_id=con, person=PERSON, now=now) is None
    with isolation.scope(tenant, TEAM_A):
        assert (await store.token(tenant, con, "test", PERSON) or {}).get("access_ct") == "sealed"


async def test_the_database_alone_hides_and_guards_them(engine: AsyncEngine, tenant: str) -> None:
    unmarked = [t.name for t in SIGN_IN_TABLES if isolation_kind(t) != "team"]
    assert not unmarked, f"not isolated by team in the database: {unmarked}"
    await _signed_in(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            for t in SIGN_IN_TABLES:
                # Only the tenant is named: the team must come from the policy.
                seen = await c.execute(sa.text(f"SELECT count(*) FROM {t.name} WHERE tenant_id = :t"), {"t": tenant})
                assert seen.scalar_one() == 0, f"team B read {t.name}"
                changed = await c.execute(
                    sa.text(f"UPDATE {t.name} SET environment = environment WHERE tenant_id = :t"), {"t": tenant}
                )
                assert changed.rowcount == 0, f"team B changed {t.name}"
    with isolation.scope(tenant, TEAM_A):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            seen = await c.execute(
                sa.text("SELECT count(*) FROM connection_tokens WHERE tenant_id = :t"), {"t": tenant}
            )
            assert seen.scalar_one() == 1


async def test_each_new_row_carries_its_connections_team(engine: AsyncEngine, tenant: str) -> None:
    await _signed_in(engine, tenant)
    async with engine.connect() as c:
        for t in (connection_tokens, oauth_states, connection_environments):
            teams = (await c.execute(sa.select(t.c.team_id).where(t.c.tenant_id == tenant))).scalars().all()
            assert teams and set(teams) == {TEAM_A}, (t.name, teams)


async def test_a_moved_connection_takes_its_rows(engine: AsyncEngine, tenant: str) -> None:
    store, con = await _signed_in(engine, tenant)
    now = datetime.now(UTC)
    with isolation.tenant_wide("TESTS", tenant_id=tenant):
        await store.change(tenant, con, 2, {"team_id": TEAM_B}, actor="dev seed", at=now)
    with isolation.scope(tenant, TEAM_B):
        found: dict[str, Any] = await store.token(tenant, con, "test", PERSON) or {}
        assert found.get("access_ct") == "sealed"
        assert [p["person_id"] for p in await store.people(tenant, con)] == [PERSON]
