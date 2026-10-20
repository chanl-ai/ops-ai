"""The dev seed with a fake OpenAI URL: a dev database whose openai-local row points elsewhere with no credential (an
old port, a real provider's URL) is repointed at the fake; one an operator bound to a real provider keeps it."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.seed import OPENAI_LOCAL, seed
from ops_models.store import provider_connections
from ops_service_kit.ids import now_iso

FAKE = "http://127.0.0.1:6199/v1"


async def test_an_existing_openai_local_is_repointed_at_the_fake(database_url: str) -> None:
    engine = create_async_engine(database_url)
    row = {"name": OPENAI_LOCAL, "type": "openai-compatible", "key_ref": None, "created_at": now_iso()}
    async with engine.begin() as c:
        await c.execute(
            postgresql.insert(provider_connections)
            .values(id=OPENAI_LOCAL, base_url="https://api.openai.com/v1", **row)
            .on_conflict_do_update(
                index_elements=["id"], set_={"base_url": "https://api.openai.com/v1", "key_ref": None}
            )
        )
    await seed(engine, FAKE)
    async with engine.connect() as c:
        q = sa.select(provider_connections.c.base_url).where(provider_connections.c.id == OPENAI_LOCAL)
        assert (await c.execute(q)).scalar_one() == FAKE
    await engine.dispose()


async def test_an_openai_local_an_operator_gave_a_credential_stays_on_its_provider(database_url: str) -> None:
    # `make demo-model MODEL=<id>` (and the shared stack's make up) bind openai-local to a real provider with a
    # credential name; a models-service restart must not quietly send the demo back to the fake.
    engine = create_async_engine(database_url)
    row = {"name": OPENAI_LOCAL, "type": "openai-compatible", "key_ref": "openai", "created_at": now_iso()}
    async with engine.begin() as c:
        await c.execute(
            postgresql.insert(provider_connections)
            .values(id=OPENAI_LOCAL, base_url="https://api.openai.com/v1", **row)
            .on_conflict_do_update(
                index_elements=["id"], set_={"base_url": "https://api.openai.com/v1", "key_ref": "openai"}
            )
        )
    await seed(engine, FAKE)
    async with engine.connect() as c:
        q = sa.select(provider_connections.c.base_url).where(provider_connections.c.id == OPENAI_LOCAL)
        assert (await c.execute(q)).scalar_one() == "https://api.openai.com/v1"
    await engine.dispose()
