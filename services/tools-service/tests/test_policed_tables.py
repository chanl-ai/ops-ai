"""Every table tools_0080 polices is held to its tenant (and team) by the database, by failure mode: a tenant reads
another tenant's row with SQL that names no tenant, another team reads a team's row, and a write lands a row in another
tenant or team. Only the policy can stop these, so each statement runs as `ops_tools_tenant`, the role every store
transaction runs as; the database user the tests connect as bypasses row security and writes the rows read here."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store import isolation
from ops_store.schema import isolation_kind
from ops_tools.store.calls import gateway_calls
from ops_tools.store.connections import ROLE
from ops_tools.store.egress import egress_audit, egress_hosts, egress_ranges
from ops_tools.store.modules import (
    module_approvals,
    module_egress_hosts,
    module_operations,
    module_versions,
    operation_mocks,
    tool_modules,
)
from ops_tools.store.plugin_bindings import plugin_bindings
from ops_tools.store.rate_windows import operation_rate_windows
from ops_tools.store.send_policies import send_checks, send_policies
from ops_tools.store.team_defaults import team_defaults

POLICED = [
    egress_audit,
    egress_hosts,
    egress_ranges,
    gateway_calls,
    module_approvals,
    module_egress_hosts,
    module_operations,
    module_versions,
    operation_mocks,
    operation_rate_windows,
    plugin_bindings,
    send_checks,
    send_policies,
    team_defaults,
]
TEAM, OTHER_TEAM = "team_cards", "team_ops"
MODULE, HOST = "mod_policed", "policed.example.com"


def _value(column: sa.Column[Any], tenant: str, n: int) -> Any:
    named = {
        "tenant_id": tenant,
        "team_id": TEAM,
        "module_id": MODULE,
        "host": HOST,
        "id": f"x_{n}_{tenant}",
        "access": "read",
    }
    if column.name in named:
        return named[column.name]
    kind = column.type
    if isinstance(kind, sa.Boolean):
        return False
    if isinstance(kind, sa.Integer | sa.Numeric | sa.Float):
        return n
    if isinstance(kind, sa.DateTime):
        return datetime.now(UTC)
    if isinstance(kind, sa.JSON):
        return {}
    length = getattr(kind, "length", None) or 40
    return f"v{n}"[:length]


def _row(table: sa.Table, tenant: str, n: int = 1) -> dict[str, Any]:
    """Every column a row must have, with the scope columns set to `tenant` and TEAM."""

    def needed(c: sa.Column[Any]) -> bool:
        if c.name in ("tenant_id", "team_id"):
            return True
        if table.autoincrement_column is c or c.server_default is not None:
            return False
        return c.primary_key or not c.nullable

    return {c.name: _value(c, tenant, n) for c in table.columns if needed(c)}


async def _parents(engine: AsyncEngine, table: sa.Table, tenant: str) -> None:
    """The module and listed host a child row's foreign keys name, written as the database owner."""
    needs = {fk.column.table.name for fk in table.foreign_keys}
    async with engine.begin() as c:
        if "egress_hosts" in needs:
            await c.execute(egress_hosts.insert().values(**_row(egress_hosts, tenant)))
        if "tool_modules" in needs:
            await c.execute(tool_modules.insert().values(**{**_row(tool_modules, tenant), "id": MODULE}))


async def _count(engine: AsyncEngine, table: sa.Table, tenant: str, team: str | None) -> int:
    with isolation.scope(tenant, team):
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            return (await c.execute(sa.select(sa.func.count()).select_from(table))).scalar_one()


@pytest.mark.parametrize("table", POLICED, ids=lambda t: t.name)
async def test_a_policed_row_is_read_and_written_only_in_its_tenant_and_team(
    engine: AsyncEngine, table: sa.Table
) -> None:
    by_team = isolation_kind(table) == "team"
    assert isolation_kind(table) in ("team", "tenant"), table.name
    tenant, elsewhere = f"t_{uuid4().hex[:10]}", f"t_{uuid4().hex[:10]}"
    await _parents(engine, table, tenant)
    async with engine.begin() as c:
        await c.execute(table.insert().values(**_row(table, tenant)))

    assert await _count(engine, table, tenant, TEAM) == 1, "the owning team reads its row"
    assert await _count(engine, table, elsewhere, TEAM) == 0, "another tenant read the row"
    assert await _count(engine, table, tenant, OTHER_TEAM) == (0 if by_team else 1), "the team policy is wrong"

    await _refused(engine, table, (elsewhere, TEAM), _row(table, tenant, 2))
    if by_team:
        await _refused(engine, table, (tenant, OTHER_TEAM), _row(table, tenant, 3))


async def _refused(engine: AsyncEngine, table: sa.Table, scope: tuple[str, str], row: dict[str, Any]) -> None:
    """The write is refused by the policy itself, never by a key or a foreign key it happens to break."""
    with isolation.scope(*scope), pytest.raises(DBAPIError) as refused:
        async with isolation.isolated_tx(engine, role=ROLE) as c:
            await c.execute(table.insert().values(**row))
    said = str(refused.value)
    assert "row-level security" in said or "block predicate" in said, said
