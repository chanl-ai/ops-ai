"""Each tenant's share of a per-tenant model key is held to that tenant by the database (c-616 C4), by failure mode:
another tenant reads a share, or spends from it, with SQL that names no tenant, which only the database policy can
stop; a per-tenant call's share and spend no longer run at all once the store moved onto the tenant role. Runs on the
test PostgreSQL as `ops_models_tenant`."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.store.keys import ModelKeys
from ops_models.store.tables import model_key_tenants, model_keys
from ops_store import isolation
from ops_store.schema import isolation_kind

from .conftest import Models

ROLE = "ops_models_tenant"


async def test_a_tenants_share_is_hidden_from_another_tenant(models: Models, database_url: str) -> None:
    assert (isolation_kind(model_key_tenants), isolation_kind(model_keys)) == ("tenant", "system")
    key_id, _ = await models.key(budget="5")
    engine = create_async_engine(database_url)
    mine, other = f"t_{uuid4().hex[:8]}", f"t_{uuid4().hex[:8]}"
    store = ModelKeys(engine)
    try:
        with isolation.scope(mine, None):
            share = await store.tenant_share(key_id, mine, Decimal("2"))
            await store.spend(key_id, Decimal("0.5"), tenant_id=mine)
        assert share["budget"] == Decimal("2")
        with isolation.scope(other, None):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                where = {"k": key_id}
                seen = await c.execute(sa.text("SELECT count(*) FROM model_key_tenants WHERE key_id = :k"), where)
                assert seen.scalar_one() == 0, "another tenant read the share"
                spent = await c.execute(
                    sa.text("UPDATE model_key_tenants SET spent = spent + 1 WHERE key_id = :k"), where
                )
                assert spent.rowcount == 0, "another tenant spent from the share"
        with isolation.scope(mine, None):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                left = await c.execute(sa.text("SELECT spent FROM model_key_tenants WHERE key_id = :k"), {"k": key_id})
                assert left.scalar_one() == Decimal("0.5")
    finally:
        await engine.dispose()
