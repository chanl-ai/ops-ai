"""What ops_tools_system, the role that reads across tenants, may read, by failure mode: it reads a tool's headers, a
module's sign-in or saved baseline, or a version's review note, any of which can hold a credential; a listing it runs
reads a column it holds no grant on and the job fails."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import (
    HEADER_KEYS,
    ModuleStore,
    module_approvals,
    module_operations,
    module_versions,
    tool_modules,
)
from ops_tools.store.review_handoffs import ReviewHandoffs
from ops_tools.store.team_defaults import TeamDefaults


@pytest.mark.parametrize(
    "column",
    [
        module_operations.c.headers,
        tool_modules.c.auth,
        tool_modules.c.baseline,
        module_versions.c.changes,
        module_approvals.c.constraints,
    ],
    ids=lambda c: f"{c.table.name}.{c.name}",
)
async def test_the_system_role_cannot_read_a_column_that_may_hold_a_credential(
    engine: AsyncEngine, column: sa.Column[object]
) -> None:
    with pytest.raises(DBAPIError, match="permission denied"):
        async with ModuleStore(engine).system_tx(HEADER_KEYS) as c:
            await c.execute(sa.select(column).limit(1))


async def test_every_cross_tenant_listing_reads_only_what_the_system_role_is_granted(
    store: ModuleStore, engine: AsyncEngine
) -> None:
    await store.header_holders()
    await ReviewHandoffs(engine).pending()
    await ReviewHandoffs(engine).open_access()
    await TeamDefaults(engine).teams()
    await TeamDefaults(engine).behind(1)
