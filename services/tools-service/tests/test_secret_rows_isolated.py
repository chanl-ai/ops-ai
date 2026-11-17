"""Sealed secret values are held by the database (proved across every locked table in C5), by failure mode:
another team reads a team's tool secrets or their audit through the store; another team reads or changes them, or a
team's own app credential, with SQL that names no team, which only the database policy can stop; the store's page
reading another team's secrets while the database lets every team through. Runs on the compose PostgreSQL as
`ops_tools_tenant`, the role every store transaction runs as, since the database user the tests connect as bypasses
row security."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_store.team_scope import acting_as
from ops_tools.store.connections import app_credentials, connection_audit
from ops_tools.store.modules import service_outbox
from ops_tools.store.secrets import SecretStore, secret_audit, tool_secrets

from .conftest import setup_tx

ROLE = "ops_tools_tenant"
# The rig connects to SQL Server as the administrator, so the service's runtime user is impersonated there.
RUNTIME = "ops_tools_runtime"
TEAM_A, TEAM_B = "team_cards", "team_ops"


@pytest.fixture
def engine(both_engine: AsyncEngine) -> AsyncEngine:
    """This file's tests run on PostgreSQL and SQL Server (conftest.database_url)."""
    return both_engine


async def _sealed(engine: AsyncEngine, tenant: str) -> SecretStore:
    """Team A's secret with its audit row, and team A's own app credential for a plugin."""
    store = SecretStore(engine)
    with isolation.scope(tenant, TEAM_A):
        await store.create(tenant, TEAM_A, "DESK_KEY", "sealed-a", actor="t", at=datetime.now(UTC))
    async with setup_tx(engine, tenant, TEAM_A) as c:
        await c.execute(
            app_credentials.insert().values(
                tenant_id=tenant,
                id="cred_a",
                team_id=TEAM_A,
                app_id="test.desk",
                name="Desk credentials",
                client_id="team-a-app",
                secret_name="DESK_KEY",
                created_by="t",
                created_at=datetime.now(UTC),
                updated_by="t",
                updated_at=datetime.now(UTC),
            )
        )
    return store


async def test_another_team_finds_no_secret_through_the_store(engine: AsyncEngine, tenant: str) -> None:
    store = await _sealed(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        assert await store.listed(tenant, TEAM_A) == []
    with isolation.scope(tenant, TEAM_A):
        assert [s.name for s in await store.listed(tenant, TEAM_A)] == ["DESK_KEY"]


async def test_the_database_alone_hides_and_guards_them(engine: AsyncEngine, tenant: str) -> None:
    assert [isolation_kind(t) for t in (tool_secrets, secret_audit, app_credentials)] == ["team", "team", "team"]
    await _sealed(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            for name in ("tool_secrets", "secret_audit", "app_credentials"):
                seen = await c.execute(sa.text(f"SELECT count(*) FROM {name} WHERE tenant_id = :t"), {"t": tenant})  # noqa: S608
                assert seen.scalar_one() == 0, f"team B read {name}"
            changed = await c.execute(
                sa.text("UPDATE tool_secrets SET version = version WHERE tenant_id = :t"), {"t": tenant}
            )
            assert changed.rowcount == 0, "team B changed team A's secret"
    with isolation.scope("t_elsewhere", TEAM_A):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            seen = await c.execute(sa.text("SELECT count(*) FROM app_credentials WHERE app_id = 'test.desk'"))
            assert seen.scalar_one() == 0, "another tenant read a team's app credential"
    with isolation.scope(tenant, TEAM_A):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            for name, rows in (("tool_secrets", 1), ("secret_audit", 1), ("app_credentials", 1)):
                seen = await c.execute(sa.text(f"SELECT count(*) FROM {name} WHERE tenant_id = :t"), {"t": tenant})  # noqa: S608
                assert seen.scalar_one() == rows, name


async def test_the_store_page_holds_the_acting_team_when_the_policy_lets_every_team_through(
    engine: AsyncEngine, tenant: str
) -> None:
    await _sealed(engine, tenant)
    with isolation.scope(tenant, TEAM_B):
        await SecretStore(engine).create(tenant, TEAM_B, "OPS_KEY", "sealed-b", actor="t", at=datetime.now(UTC))
    # Tenant-wide with a team acting, so the database policy lets every team through and the query alone holds them.
    wide = isolation.tenant_wide("a test reads the secrets list with every team let through", tenant_id=tenant)
    with wide, acting_as(TEAM_A):
        _, mine = await SecretStore(engine).page(tenant, TEAM_A, ListParams())
        _, theirs = await SecretStore(engine).page(tenant, TEAM_B, ListParams())
    assert ([x.name for x in mine], theirs) == (["DESK_KEY"], [])


async def test_the_tenant_role_cannot_rewrite_an_audit_or_outbox_row(engine: AsyncEngine, tenant: str) -> None:
    """Audit and outbox rows are added, never changed or removed, by a tenant's transaction: as `ops_tools_tenant` on
    PostgreSQL and the runtime user on SQL Server (the relay and the audit sweep run as the system role)."""
    statements = {
        f"{verb} {t.name}": (t.update().values(tenant_id=tenant) if verb == "update" else t.delete()).where(
            t.c.tenant_id == tenant
        )
        for t in (connection_audit, secret_audit, service_outbox)
        for verb in ("update", "delete")
    }
    for name, statement in statements.items():
        with isolation.scope(tenant, TEAM_A):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                mssql = c.dialect.name == "mssql"
                if mssql:
                    await c.execute(sa.text(f"EXECUTE AS USER = N'{RUNTIME}'"))
                with pytest.raises(DBAPIError) as e:
                    async with isolation.attempt(c):
                        await c.execute(statement)
                if mssql:
                    await c.execute(sa.text("REVERT"))
        assert "permission" in str(e.value).lower() and "denied" in str(e.value).lower(), name
