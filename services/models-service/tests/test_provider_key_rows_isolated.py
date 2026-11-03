"""An account's model provider keys are held to their tenant by the database, by failure mode: another
account reads them through the store; another account reads or changes them with SQL that names no tenant, which only
the database policy can stop. Runs on the test PostgreSQL as `ops_models_tenant`, the role every provider key
transaction runs as, since the database user the tests connect as bypasses row security."""

from __future__ import annotations

from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.store import ProviderKeyStore
from ops_models.store.tables import provider_keys
from ops_service_kit.credentials import credential_store
from ops_service_kit.settings import Settings
from ops_store import isolation
from ops_store.schema import isolation_kind

ROLE = "ops_models_tenant"


async def test_another_account_reads_no_provider_key_through_the_store_or_the_database(database_url: str) -> None:
    assert isolation_kind(provider_keys) == "tenant"
    engine = create_async_engine(database_url)
    mine, other = f"t_{uuid4().hex[:8]}", f"t_{uuid4().hex[:8]}"
    store = ProviderKeyStore(engine, credential_store(Settings()))
    try:
        with isolation.scope(mine, None):
            await store.save(mine, "openai", "sk-mine-0001", by="admin@bank.example")
        with isolation.scope(other, None):
            assert await store.listed(mine) == []
            assert await store.value(mine, "openai") is None
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                seen = await c.execute(sa.text("SELECT count(*) FROM provider_keys WHERE name = 'openai'"))
                assert seen.scalar_one() == 0, "another account read the key"
                changed = await c.execute(sa.text("UPDATE provider_keys SET version = version WHERE name = 'openai'"))
                assert changed.rowcount == 0, "another account changed the key"
        with isolation.scope(mine, None):
            assert await store.value(mine, "openai") == "sk-mine-0001"
    finally:
        await engine.dispose()
