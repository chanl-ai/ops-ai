"""Each background job tools-service runs reads and writes the rows it should under the row policies, with two
tenants' data in the database, by failure mode: the relay delivers one tenant's events and leaves the other's, or posts
an event as the wrong tenant or team; the sign-in keep-alive refreshes one tenant's sign-ins and lets the other's
lapse; the secret audit sweep deletes only one tenant's old rows, or a tenant's recent ones; the seed load for a second
tenant finds the first tenant's modules and adds nothing, or rewrites them; and the team-default catch-up brings one
tenant's teams up to date and leaves the other's behind, or writes a team's copy into the other tenant. A job that
logs no error can still have done any of these, which is what each test reads back."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.background import BY_KEY
from ops_store.outbox import add as add_event
from ops_tools.defaults import DEFAULTS_VERSION, catch_up
from ops_tools.modules.seed import load
from ops_tools.store.connections import SHARED, connection_tokens
from ops_tools.store.modules import ModuleStore, service_outbox
from ops_tools.store.relay import tools_relay
from ops_tools.store.secrets import AUDIT_KEPT_S, AUDIT_RETENTION, AUDIT_SWEEP, SecretStore, secret_audit
from ops_tools.store.team_defaults import TeamDefaults
from ops_tools.store.tenancy import ROLE

from .conftest import setup_tx
from .test_personal_sign_in import TEAM, connection
from .test_sign_in_keepalive import IDLE, System, rig


@pytest.fixture
def engine(both_engine: AsyncEngine) -> AsyncEngine:
    """These jobs run on PostgreSQL and SQL Server (conftest.database_url): each reads across tenants as the system
    role, which each database lets through its row policies differently."""
    return both_engine


def _other() -> str:
    return f"t_{uuid4().hex[:10]}"


class Agents:
    """agents-service's event routes: records each post with the tenant and team it was sent as."""

    def __init__(self) -> None:
        self.posts: list[tuple[str, str, str, str]] = []

    async def post(self, path: str, body: Any, /, *, tenant: str, team: str) -> None:
        self.posts.append((path, str(body["key"]), tenant, team))


async def test_the_relay_sends_each_tenants_events_as_that_tenant_and_marks_both(
    engine: AsyncEngine, tenant: str
) -> None:
    other = _other()
    mine = {(tenant, "team_ops"): f"k_{tenant}", (other, "team_cards"): f"k_{other}"}
    async with engine.begin() as c:
        for (t, team), key in mine.items():
            await add_event(c, service_outbox, tenant_id=t, team_id=team, name="tool.test", key=key, payload={})
    agents = Agents()
    relay = tools_relay(engine, agents)
    # Other tests' events may be due first; a pass takes a batch, so pass until both of these are out.
    for _ in range(50):
        if {k for _, k, _, _ in agents.posts} >= set(mine.values()):
            break
        await relay.once()
    sent = {(t, team): key for _, key, t, team in agents.posts if key in mine.values()}
    assert sent == mine, agents.posts
    assert {p for p, k, _, _ in agents.posts if k in mine.values()} == {"/v1/events"}
    o = service_outbox.c
    async with engine.connect() as c:
        marked = await c.execute(sa.select(o.event_key, o.sent_at).where(o.event_key.in_(list(mine.values()))))
        assert {k: at is not None for k, at in marked} == dict.fromkeys(mine.values(), True)


async def test_the_keepalive_refreshes_each_tenants_idle_sign_in_in_its_own_tenant(
    engine: AsyncEngine, tenant: str
) -> None:
    other = _other()
    system = System()
    store, tokens, keepalive = rig(engine, system)
    held: dict[str, str] = {}
    k = connection_tokens.c
    for t in (tenant, other):
        await TeamDefaults(engine).record(t, TEAM, 1, datetime.now(UTC))
        with isolation.scope(t, TEAM):
            held[t] = await connection(store, t, "team")
            answer = {"access_token": f"at-{t}", "expires_in": 3600, "refresh_token": f"rt-{t}"}
            await tokens.store_answer(t, held[t], answer, SHARED)
            async with setup_tx(engine, t, TEAM) as c:
                await c.execute(
                    connection_tokens.update()
                    .where(k.tenant_id == t, k.connection_id == held[t], k.person_id == SHARED)
                    .values(refreshed_at=datetime.now(UTC) - IDLE)
                )
    await keepalive.once()
    assert {f"rt-{tenant}", f"rt-{other}"} <= set(system.refreshed), system.refreshed
    recent = datetime.now(UTC) - timedelta(minutes=5)
    for t, con in held.items():
        with isolation.scope(t, TEAM):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                at = (
                    await c.execute(
                        sa.select(k.refreshed_at).where(k.tenant_id == t, k.connection_id == con, k.person_id == SHARED)
                    )
                ).scalar_one()
        assert at > recent, f"{t}'s sign-in was not refreshed in its own tenant"


async def test_the_audit_sweep_deletes_every_tenants_old_rows_and_keeps_recent_ones(
    engine: AsyncEngine, tenant: str
) -> None:
    other = _other()
    now = datetime.now(UTC)
    old = now - timedelta(seconds=AUDIT_KEPT_S + 86400)
    for t in (tenant, other):
        async with setup_tx(engine, t, TEAM) as c:
            for name, at in (("OLD", old), ("NEW", now)):
                row = {"tenant_id": t, "team_id": TEAM, "name": name, "action": "used", "version": 1, "actor": "t"}
                await c.execute(secret_audit.insert().values(**row, at=at))
    sweep = BY_KEY[AUDIT_SWEEP].sweep
    assert sweep is not None
    # As the service runs it: the system role, in the transaction run_sweep opens.
    async with SecretStore(engine).system_tx(AUDIT_RETENTION) as c:
        await sweep(c, time.time())
    a = secret_audit.c
    left: list[tuple[str, str]] = []
    for t in (tenant, other):
        async with setup_tx(engine, t, TEAM) as c:
            left += [
                (r.tenant_id, r.name) for r in await c.execute(sa.select(a.tenant_id, a.name).where(a.tenant_id == t))
            ]
    assert sorted(left) == sorted([(tenant, "NEW"), (other, "NEW")])


async def test_the_seed_load_writes_each_tenants_modules_and_leaves_the_others(
    store: ModuleStore, seed: dict[str, Any], tenant: str
) -> None:
    other = _other()
    now = datetime.now(UTC)
    first = await load(store, seed, tenant_id=tenant, now=now)
    assert first > 0
    assert await load(store, seed, tenant_id=other, now=now) == first, "the second tenant found the first one's"
    assert await store.count(tenant) == await store.count(other) == first
    assert await load(store, seed, tenant_id=tenant, now=now) == 0, "the second tenant's load changed the first's"
    core = await store.get(other, "mod_core_banking")
    assert core is not None and core["tenant_id"] == other


async def test_the_catch_up_brings_each_tenants_teams_up_to_date_in_their_own_tenant(
    store: ModuleStore, engine: AsyncEngine, tenant: str
) -> None:
    other = _other()
    defaults = TeamDefaults(engine)
    behind = {(tenant, "team_retail"), (other, "team_ops")}
    for t, team in behind:
        await defaults.record(t, team, 0, datetime.now(UTC))
    assert behind <= set(await catch_up(store, defaults))
    for t, team in behind:
        assert await defaults.version(t, team) == DEFAULTS_VERSION
        assert await store.get(t, f"mod_builtin_knowledge_{team}") is not None
    assert await store.get(other, "mod_builtin_knowledge_team_retail") is None, "a team's copy reached another tenant"
    assert await store.get(tenant, "mod_builtin_knowledge_team_ops") is None, "a team's copy reached another tenant"
