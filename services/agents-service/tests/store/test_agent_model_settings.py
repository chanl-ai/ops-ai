"""The builder's model settings on an agent version (`spec["modelSettings"]`, knob name to value), by failure mode: a
save that changes only the settings recorded as no change, so the review and history hide it; a version saved before
the key existed reported as changed when it is next saved with no settings; a published version's settings rewritten
by a later save, so what runs changes without a publish."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.agent_registry import AgentRegistry
from ops_service_kit.http import Json
from ops_store import isolation

TEAM = "team_cards"


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


def _spec(**extra: Json) -> Json:
    return {"name": f"Card desk {uuid4().hex[:6]}", "role": "Answers card questions", "model": "fast", **extra}


async def test_a_save_that_changes_only_the_model_settings_records_the_change(engine: AsyncEngine, tenant: str) -> None:
    agents = AgentRegistry(engine)
    with isolation.scope(tenant, TEAM):
        spec = _spec(modelSettings={"temperature": 0.2})
        aid = await agents.create(spec, by="builder", team_id=TEAM)
        await agents.publish(aid, 1, by="builder", review_id="r1")
        n = await agents.save(aid, {**spec, "modelSettings": {"temperature": 0.7}}, by="builder")
        saved = await agents.version(aid, n)
    assert saved.changes == ["Changed model settings"]


async def test_a_version_saved_before_the_key_is_not_changed_by_empty_settings(
    engine: AsyncEngine, tenant: str
) -> None:
    agents = AgentRegistry(engine)
    with isolation.scope(tenant, TEAM):
        spec = _spec()
        aid = await agents.create(spec, by="builder", team_id=TEAM)
        await agents.publish(aid, 1, by="builder", review_id="r1")
        n = await agents.save(aid, {**spec, "modelSettings": {}}, by="builder")
        saved = await agents.version(aid, n)
    assert saved.changes == ["No changes"]


async def test_a_published_version_keeps_its_settings_after_a_later_save(engine: AsyncEngine, tenant: str) -> None:
    agents = AgentRegistry(engine)
    with isolation.scope(tenant, TEAM):
        spec = _spec(modelSettings={"temperature": 0.2, "maxTokens": 800})
        aid = await agents.create(spec, by="builder", team_id=TEAM)
        await agents.publish(aid, 1, by="builder", review_id="r1")
        n = await agents.save(aid, {**spec, "modelSettings": {"temperature": 1.0}}, by="builder")
        served = await agents.published_spec(aid, 1)
        draft = await agents.version(aid, n)
    assert n == 2
    assert served is not None and served["modelSettings"] == {"temperature": 0.2, "maxTokens": 800}
    assert draft.spec["modelSettings"] == {"temperature": 1.0}
