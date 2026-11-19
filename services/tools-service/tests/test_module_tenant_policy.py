"""tool_modules is held to its tenant by the database (tools_0086), by failure mode: another tenant reads, changes or
deletes a module with SQL that names no tenant, or writes a module into a tenant it is not acting in; and the
migration leaves the table unpoliced, fails on a second run, or leaves the policy behind on the way down. The team is
held in code (store/modules.py `team_modules`), so another team of the same tenant still sees the row here. Each
statement runs as `ops_tools_tenant`, the role every store transaction runs as."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_store import isolation
from ops_tools.store.modules import tool_modules
from ops_tools.store.tenancy import ROLE

from .conftest import setup_tx
from .test_policed_tables import OTHER_TEAM, TEAM, _row  # pyright: ignore[reportPrivateUsage]
from .test_registry_store import _alembic, scratch_database  # pyright: ignore[reportPrivateUsage]

BEFORE, HEAD = "tools_0085_module_list_indexes", "tools_0086_module_tenant_policy"
MODULE = "mod_tenant_policy"


@pytest.fixture
def engine(both_engine: AsyncEngine) -> AsyncEngine:
    """This file's policy test runs on PostgreSQL and SQL Server (conftest.database_url)."""
    return both_engine


async def _as(engine: AsyncEngine, tenant: str, team: str, statement: sa.Executable) -> Any:
    with isolation.scope(tenant, team):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            result = await c.execute(statement)
            return result.scalar_one() if result.returns_rows else result.rowcount


def _count() -> sa.Select[int]:
    return sa.select(sa.func.count()).select_from(tool_modules).where(tool_modules.c.id == MODULE)


@pytest.mark.parametrize("action", ["read", "update", "delete", "insert"])
async def test_another_tenant_never_reads_changes_or_writes_a_module(engine: AsyncEngine, action: str) -> None:
    tenant, elsewhere = f"t_{uuid4().hex[:10]}", f"t_{uuid4().hex[:10]}"
    async with setup_tx(engine, tenant, TEAM) as c:
        await c.execute(tool_modules.insert().values(**{**_row(tool_modules, tenant), "id": MODULE}))
    where = tool_modules.c.id == MODULE

    if action == "read":
        assert await _as(engine, elsewhere, TEAM, _count()) == 0, "another tenant read the module"
        assert await _as(engine, tenant, OTHER_TEAM, _count()) == 1, "the policy is by team, not by tenant"
    elif action == "update":
        changed = tool_modules.update().where(where).values(description="moved")
        assert await _as(engine, elsewhere, TEAM, changed) == 0, "another tenant changed the module"
    elif action == "delete":
        assert await _as(engine, elsewhere, TEAM, tool_modules.delete().where(where)) == 0, "another tenant deleted it"
    else:
        # A tenant that holds no module yet: SQL Server checks a key before its block predicate, so a row repeating
        # the first one's key would be refused by the key and prove nothing.
        fresh = f"t_{uuid4().hex[:10]}"
        written = tool_modules.insert().values(**{**_row(tool_modules, fresh), "id": "m2"})
        with pytest.raises(DBAPIError) as refused:
            await _as(engine, elsewhere, TEAM, written)
        said = str(refused.value)
        assert "row-level security" in said or "block predicate" in said, said

    held = sa.select(tool_modules.c.description).where(where)
    assert await _as(engine, tenant, TEAM, held) != "moved", "the owner's module changed"


async def _policy(url: str) -> list[tuple[str, bool, bool]]:
    """tool_modules' policies, with whether row-level security is on and forced."""
    engine = create_async_engine(url)
    try:
        async with engine.connect() as c:
            on = (
                await c.execute(
                    sa.text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'tool_modules'")
                )
            ).one()
            names = (
                await c.execute(sa.text("SELECT policyname FROM pg_policies WHERE tablename = 'tool_modules'"))
            ).scalars()
            return [(str(n), bool(on[0]), bool(on[1])) for n in names] or [("", bool(on[0]), bool(on[1]))]
    finally:
        await engine.dispose()


async def test_tools_0086_polices_modules_reruns_and_reverts() -> None:
    async with scratch_database("tools_module_policy") as target:
        _alembic(target, "upgrade", BEFORE)
        assert await _policy(target) == [("", False, False)]
        _alembic(target, "upgrade", HEAD)
        _alembic(target, "stamp", BEFORE)
        _alembic(target, "upgrade", HEAD)
        assert await _policy(target) == [("tool_modules_tenant", True, True)]
        _alembic(target, "downgrade", BEFORE)
        assert await _policy(target) == [("", False, False)]
