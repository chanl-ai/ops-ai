"""The dev seed with a fake OpenAI URL: a dev database whose openai-local row points elsewhere with no credential (an
old port, a real provider's URL) is repointed at the fake; one an operator bound to a real provider keeps it."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import create_async_engine

from ops_models.seed import OPENAI_LOCAL, seed
from ops_models.store import provider_connections
from ops_models.store.tables import model_aliases
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


async def test_the_assistant_gets_its_own_alias_beside_default_with_no_reasoning_effort(database_url: str) -> None:
    # The team assistant ran on `default`, so moving its model moved every agent's; and gpt-5.5 refuses function
    # tools with any reasoning effort on chat completions, so a seeded effort would refuse every assistant turn.
    engine = create_async_engine(database_url)
    await seed(engine, FAKE)
    async with engine.connect() as c:
        q = sa.select(model_aliases.c.name, model_aliases.c.provider_id, model_aliases.c.reasoning_effort).where(
            model_aliases.c.name.in_(("default", "assistant")), model_aliases.c.status == "current"
        )
        rows = {r.name: (r.provider_id, r.reasoning_effort) for r in await c.execute(q)}
    assert rows == {"default": (OPENAI_LOCAL, None), "assistant": (OPENAI_LOCAL, None)}, rows
    await engine.dispose()
