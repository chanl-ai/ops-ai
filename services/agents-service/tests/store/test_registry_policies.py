"""The registry, graph version and channel tables are held to their tenant (and team) by the database (agents 0109),
on PostgreSQL and on SQL Server, by failure mode: tenant B reads, updates, deletes or writes tenant A's row of any of
them, with raw SQL and no WHERE clause as ops_runtime_tenant; a widget or workflow version is reached through another
tenant's parent; two tenants cannot hold one widget id or one deployment id; a read inside a tenant-wide scope with a
team acting loses the code's own team predicate, which is all that stands there; another team's deployment id is
written over or fails with a database error instead of a Conflict (on SQL Server the insert hits the key, since the
existence check sees only the acting team's rows); the agents system user reads a table or column it was never
granted; and the policies do not survive the step down and back up."""

from __future__ import annotations

import asyncio
import os
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import (
    agent_skill_pins,
    publish_requests,
    registry_agent_versions,
    registry_agents,
)
from ops_agents.store.background import background_heartbeats
from ops_agents.store.cases import case_events, cases
from ops_agents.store.channels import (
    ChannelStore,
    Deployment,
    channel_cursors,
    channel_messages,
    deployments,
    thread_inbox,
)
from ops_agents.store.graphs import graph_versions
from ops_agents.store.guardrails import registry_guardrail_versions, registry_guardrails
from ops_agents.store.skills import registry_skill_versions, registry_skills
from ops_agents.store.tenancy import OWNER, SYSTEM_ROLE, TENANT_ROLE
from ops_agents.store.trigger_events import trigger_events
from ops_agents.store.widget_keys import widget_mint_key_audit
from ops_agents.store.widgets import WidgetRegistry, registry_widget_versions, registry_widgets
from ops_agents.store.workflow_registry import registry_validations, registry_workflow_versions, registry_workflows
from ops_service_kit.errors import Conflict
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.conformance import RowFill, isolation_suite
from ops_store.schema import isolation_kind
from ops_store.team_scope import acting_as
from ops_store.testing import DATABASES, NO_SQL_SERVER, sql_server_schema

ROOT = Path(__file__).resolve().parents[2]
CONFIG = str(ROOT / "alembic.ini")
BEFORE = "0108_registry_tenant_keys"
REASON = "test: the agents system user reads only what it was granted"
TEAM = (
    registry_agents,
    registry_guardrails,
    registry_skills,
    registry_widgets,
    registry_workflows,
    deployments,
    agent_skill_pins,
)
TENANT = (
    publish_requests,
    registry_agent_versions,
    registry_guardrail_versions,
    registry_skill_versions,
    registry_validations,
    graph_versions,
    channel_messages,
    channel_cursors,
    thread_inbox,
)
# A version's composite key to its parent refuses a row of another tenant before any policy could; tested by hand.
CASCADED = (registry_widget_versions, registry_workflow_versions)
POLICED = frozenset(t.name for t in (*TEAM, *TENANT, *CASCADED))
PARENTS = {
    "agent_skill_pins": (registry_agents, "agent_id"),
    "registry_agent_versions": (registry_agents, "agent_id"),
    "registry_guardrail_versions": (registry_guardrails, "guardrail_id"),
    "registry_skill_versions": (registry_skills, "skill_id"),
}
MSSQL_FILTERED = sa.text(
    "SELECT OBJECT_NAME(sp.target_object_id) FROM sys.security_predicates sp "
    "JOIN sys.security_policies p ON p.object_id = sp.object_id WHERE p.is_enabled = 1 AND sp.predicate_type = 0"
)
PG_FILTERED = sa.text(
    "SELECT c.relname FROM pg_class c WHERE c.relrowsecurity AND c.relforcerowsecurity "
    "AND EXISTS (SELECT 1 FROM pg_policies p WHERE p.tablename = c.relname)"
)


@pytest.fixture(scope="module", params=DATABASES)
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(CONFIG), "head")
        yield Settings().database_url
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        yield u


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    yield e
    await e.dispose()


def _tag(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


def _value(column: sa.Column[Any]) -> Any:
    kind = column.type
    if isinstance(kind, sa.Boolean):
        return False
    if isinstance(kind, sa.Integer):
        return 1
    if isinstance(kind, sa.JSON):
        return {}
    if isinstance(kind, sa.String):
        return secrets.token_hex(8)[: kind.length or 16]
    return ""


def _row(table: sa.Table, tenant: str, team: str | None, **values: Any) -> dict[str, Any]:
    """Every column a row needs, by type, with `values` on top."""
    out = {
        c.name: _value(c)
        for c in table.columns
        if c.primary_key or (not c.nullable and c.default is None and c.server_default is None)
    }
    out["tenant_id"] = tenant
    if team is not None:
        out["team_id"] = team
    return {**out, **values}


async def _parents(engine: AsyncEngine, tenant: str) -> dict[str, str]:
    """A parent row per version table whose foreign key names its parent by id alone."""
    ids: dict[str, str] = {}
    for name, (parent, _column) in PARENTS.items():
        ids[name] = _tag("parent")
        await _as(engine, tenant, "team_p", parent.insert().values(_row(parent, tenant, "team_p", id=ids[name])))
    return ids


def _parent_fill(column: str, parent_id: str) -> RowFill:
    def fill(_tenant: str, _team: str | None) -> dict[str, Any]:
        return {column: parent_id}

    return fill


async def _as(engine: AsyncEngine, tenant: str, team: str | None, statement: sa.Executable) -> Any:
    """One statement as ops_runtime_tenant in `tenant` (and `team`, else tenant-wide)."""
    if team is None:
        with isolation.tenant_wide(OWNER, tenant_id=tenant):
            async with isolation.isolated_tx(engine, role=TENANT_ROLE) as c:
                return await c.execute(statement)
    with isolation.scope(tenant, team):
        async with isolation.isolated_tx(engine, role=TENANT_ROLE) as c:
            return await c.execute(statement)


async def test_each_registry_and_channel_table_holds_a_tenant_and_team_to_its_rows(engine: AsyncEngine) -> None:
    assert [isolation_kind(t) for t in TEAM] == ["team"] * len(TEAM)
    assert [isolation_kind(t) for t in (*TENANT, *CASCADED)] == ["tenant"] * (len(TENANT) + len(CASCADED))
    parent_ids = await _parents(engine, _tag("iso_parents"))
    fill: dict[str, RowFill] = {name: _parent_fill(key, parent_ids[name]) for name, (_p, key) in PARENTS.items()}
    assert await isolation_suite(engine, (*TEAM, *TENANT), role=TENANT_ROLE, fill=fill) == []
    # The suite reads, writes and updates; a delete is filtered by the same predicate, checked here on every table.
    a, b = _tag("t_a"), _tag("t_b")
    held: list[str] = []
    for table in (*TEAM, *TENANT):
        extra = fill[table.name](a, None) if table.name in fill else {}
        await _as(engine, a, None, table.insert().values(_row(table, a, "team_a" if table in TEAM else None, **extra)))
        if (await _as(engine, b, None, table.delete())).rowcount:
            held.append(table.name)
        if (await _as(engine, a, None, sa.select(sa.func.count()).select_from(table))).scalar_one() != 1:
            held.append(f"{table.name}: tenant A lost its row")
        await _as(engine, a, None, table.delete())
    assert held == [], "tenant B deleted tenant A's rows"


async def test_a_widget_or_workflow_version_is_held_to_its_tenant(engine: AsyncEngine) -> None:
    a, b = _tag("t_a"), _tag("t_b")
    for parent, child, column in (
        (registry_widgets, registry_widget_versions, "widget_id"),
        (registry_workflows, registry_workflow_versions, "workflow_id"),
    ):
        pid = _tag("p")
        for tenant in (a, b):
            await _as(engine, tenant, None, parent.insert().values(_row(parent, tenant, "team_a", id=pid)))
        await _as(engine, a, None, child.insert().values(_row(child, a, None, **{column: pid, "version": 1})))
        assert (await _as(engine, b, None, sa.select(sa.func.count()).select_from(child))).scalar_one() == 0
        assert (await _as(engine, b, None, child.update().values(version=2))).rowcount == 0
        assert (await _as(engine, b, None, child.delete())).rowcount == 0
        # B's parent holds the same id, so the key would take the row; only the policy refuses tenant A's name on it.
        with pytest.raises(DBAPIError):
            await _as(engine, b, None, child.insert().values(_row(child, a, None, **{column: pid, "version": 3})))
        assert (await _as(engine, a, None, sa.select(child.c.version))).scalars().all() == [1]
        for tenant in (a, b):
            await _as(engine, tenant, None, parent.delete())


async def test_two_tenants_hold_one_widget_id_and_one_deployment_id(engine: AsyncEngine) -> None:
    a, b, widget, deployment = _tag("t_a"), _tag("t_b"), _tag("wd"), _tag("dep")
    for tenant in (a, b):
        with isolation.scope(tenant, "team_a"), acting_as("team_a"):
            await WidgetRegistry(engine).create(
                widget, {"name": f"Card {tenant}"}, team_id="team_a", by="maya@x.example"
            )
            await ChannelStore(engine).put_deployment(
                Deployment(deployment, f"graph-{tenant}", "email", False, "enqueue", None, "team_a"), "2026-11-16"
            )
    for tenant in (a, b):
        with isolation.scope(tenant, "team_a"), acting_as("team_a"):
            assert (await WidgetRegistry(engine).row(widget)).name == f"Card {tenant}"
            found = await ChannelStore(engine).deployment(deployment)
            assert found is not None and found.graph == f"graph-{tenant}"


async def test_a_tenant_wide_read_with_a_team_acting_keeps_the_codes_team_predicate(engine: AsyncEngine) -> None:
    tenant, deployment = _tag("t_a"), _tag("dep")
    with isolation.scope(tenant, "team_b"), acting_as("team_b"):
        await ChannelStore(engine).put_deployment(
            Deployment(deployment, "chat", "email", False, "enqueue", None, "team_b"), "2026-11-16"
        )
    # The tenant-wide scope opens every team's rows to the policy, so only the store's team_visible stands.
    with isolation.tenant_wide(OWNER, tenant_id=tenant), acting_as("team_a"):
        assert await ChannelStore(engine).deployment(deployment) is None
    with isolation.tenant_wide(OWNER, tenant_id=tenant), acting_as("team_b"):
        assert await ChannelStore(engine).deployment(deployment) is not None


async def test_another_teams_deployment_id_is_a_conflict_and_stays_theirs(engine: AsyncEngine) -> None:
    tenant, deployment = _tag("t_a"), _tag("dep")
    with isolation.scope(tenant, "team_b"), acting_as("team_b"):
        await ChannelStore(engine).put_deployment(
            Deployment(deployment, "theirs", "email", False, "enqueue", None, "team_b"), "2026-11-16"
        )
    with isolation.scope(tenant, "team_a"), acting_as("team_a"), pytest.raises(Conflict):
        await ChannelStore(engine).put_deployment(
            Deployment(deployment, "mine", "email", False, "enqueue", None, "team_a"), "2026-11-16"
        )
    with isolation.scope(tenant, "team_b"), acting_as("team_b"):
        found = await ChannelStore(engine).deployment(deployment)
        assert found is not None and found.graph == "theirs"


async def test_the_system_user_reads_the_agent_pointers_and_is_refused_the_rest(engine: AsyncEngine) -> None:
    pointers = sa.select(registry_agents.c.tenant_id, registry_agents.c.id, registry_agents.c.published_version)
    async with isolation.system_tx(engine, REASON, role=SYSTEM_ROLE) as c:
        await c.execute(pointers.limit(1))
    for refused in (sa.select(registry_agents.c.slug), sa.select(registry_widgets.c.id), sa.select(deployments.c.id)):
        with pytest.raises(DBAPIError):
            async with isolation.system_tx(engine, REASON, role=SYSTEM_ROLE) as c:
                await c.execute(refused.limit(1))


# The runtime user the rig impersonates on SQL Server, where it connects as the administrator.
RUNTIME = "ops_agents_runtime"


async def test_a_tenants_transaction_is_refused_what_the_tenant_role_lacks(engine: AsyncEngine) -> None:
    """An append-only log is never changed or emptied, a case is never deleted, a trigger event is settled but what
    fired it is never rewritten, and heartbeats are the system user's alone: as ops_runtime_tenant on PostgreSQL and
    the runtime user on SQL Server (deploy/database/mssql.py RUNTIME_GRANTS)."""
    tenant = _tag("t_a")
    statements = {
        "update case_events": case_events.update().values(kind="x").where(case_events.c.tenant_id == tenant),
        "delete case_events": case_events.delete().where(case_events.c.tenant_id == tenant),
        "delete cases": cases.delete().where(cases.c.tenant_id == tenant),
        "delete widget_mint_key_audit": widget_mint_key_audit.delete().where(
            widget_mint_key_audit.c.tenant_id == tenant
        ),
        "update trigger_events.subject": trigger_events.update()
        .values(subject="x")
        .where(trigger_events.c.tenant_id == tenant),
        "delete trigger_events": trigger_events.delete().where(trigger_events.c.tenant_id == tenant),
        "delete background_heartbeats": background_heartbeats.delete(),
    }
    for name, statement in statements.items():
        with isolation.scope(tenant, "team_a"):
            async with isolation.isolated_tx(engine, role=TENANT_ROLE) as c:
                mssql = c.dialect.name == "mssql"
                if mssql:
                    await c.execute(sa.text(f"EXECUTE AS USER = N'{RUNTIME}'"))
                with pytest.raises(DBAPIError) as e:
                    async with isolation.attempt(c):
                        await c.execute(statement)
                if mssql:
                    await c.execute(sa.text("REVERT"))
        assert "permission" in str(e.value).lower() and "denied" in str(e.value).lower(), name


def _filtered(url: str) -> set[str]:
    async def read() -> set[str]:
        e = create_async_engine(url)
        try:
            async with e.connect() as c:
                query = MSSQL_FILTERED if c.dialect.name == "mssql" else PG_FILTERED
                return {str(r[0]) for r in await c.execute(query)} & POLICED
        finally:
            await e.dispose()

    return asyncio.run(read())


def _pinned_agent(url: str, tenant: str) -> str:
    """An agent whose older version pins one skill and whose newest pins two, one of them twice (the first at the
    higher version, which the store keeps), beside entries no pin can come from, written with no `agent_skill_pins`
    rows, as an agent saved before agents 0113 is."""
    agent = _tag("ag")

    async def write() -> None:
        e = create_async_engine(url)
        try:
            a, v = registry_agents, registry_agent_versions
            await _as(e, tenant, "team_p", a.insert().values(_row(a, tenant, "team_p", id=agent, version=2)))
            pins: list[Any] = [
                {"skillId": "sk_a", "version": 3},
                {"skillId": "sk_b", "version": 1},
                {"skillId": "sk_a", "version": 2},
                {"skillId": "sk_c", "version": 1.5},
                {"skillId": "sk_d", "version": "abc"},
                {"skillId": "s" * 70, "version": 1},
                {"skillId": "sk_e"},
                "sk_f",
            ]
            for n, held in ((1, [{"skillId": "sk_old", "version": 1}]), (2, pins)):
                row = _row(v, tenant, None, agent_id=agent, version=n, spec={"name": agent, "skillPins": held})
                await _as(e, tenant, None, v.insert().values(row))
        finally:
            await e.dispose()

    asyncio.run(write())
    return agent


def _pins(url: str, tenant: str, agent: str) -> set[tuple[str, int, str, str]]:
    async def read() -> set[tuple[str, int, str, str]]:
        e = create_async_engine(url)
        try:
            p = agent_skill_pins.c
            q = sa.select(p.skill_id, p.version, p.team_id, p.tenant_id).where(p.agent_id == agent)
            return {(str(s), int(n), str(t), str(x)) for s, n, t, x in (await _as(e, tenant, None, q)).all()}
        finally:
            await e.dispose()

    return asyncio.run(read())


def test_the_policies_come_off_with_the_step_and_back_with_it(url: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Down past agents 0113 and up again also fills `agent_skill_pins` from each agent's newest version."""
    # The chain runs against the database this case is on: env.py reads the address from Settings.
    monkeypatch.setenv("OPS_DATABASE_URL", url)
    assert _filtered(url) == POLICED
    tenant = _tag("t_pins")
    agent = _pinned_agent(url, tenant)
    assert _pins(url, tenant, agent) == set()
    try:
        command.downgrade(Config(CONFIG), BEFORE)
        # Its tenant policy predates the step (agents 0067 on PostgreSQL, the baseline on SQL Server).
        assert _filtered(url) == {publish_requests.name}
    finally:
        command.upgrade(Config(CONFIG), "head")
    assert _filtered(url) == POLICED
    assert _pins(url, tenant, agent) == {("sk_a", 3, "team_p", tenant), ("sk_b", 1, "team_p", tenant)}
