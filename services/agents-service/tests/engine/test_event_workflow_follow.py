"""A shipped event workflow that changed in the seed file (c-288, tick 30), on PostgreSQL, by failure mode: the change
goes live without the workspace's publish review; it never reaches a tenant still on the seed's version, even where no
review is needed; a second event opens a second request; a tenant whose live version a person published has it
replaced; nothing records that the shipped version moved."""

from __future__ import annotations

import copy
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.engine_lifecycle import KIND
from ops_agents.api.service_events import SEED, UPDATE_AVAILABLE, UPDATED, ensure_event_workflows
from ops_agents.store.agent_registry import AgentRegistry
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.service_events import ServiceEvents
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import DefinitionStore
from ops_service_kit.ids import now_iso
from tests.api.test_service_events import event_workflow


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


def shipped(note: str) -> dict[str, Any]:
    """The test event workflow as the seed file ships it, its End's outcome changed to tell versions apart."""
    item = copy.deepcopy(event_workflow())
    for n in item["nodes"]:
        if n["type"] == "ops.flow.end":
            n["parameters"]["outcome"] = note
    return item


class Policies:
    """publishReview as platform-service answers it; `{}` names no team, so a change is reviewed (major)."""

    def __init__(self, review: dict[str, Any]) -> None:
        self.review = review

    async def value(self, key: str) -> Any:
        return self.review if key == "publishReview" else None


async def provision(
    engine: AsyncEngine, tenant: str, item: dict[str, Any], review: dict[str, Any] | None = None
) -> None:
    rt: Any = SimpleNamespace(
        db=engine,
        event_workflows=[item],
        event_workflows_seen=set(),
        policies=Policies(review or {}),
        settings=SimpleNamespace(registry_auto_approve=False, environment="test"),
    )
    with tenant_scope(tenant):
        await ensure_event_workflows(rt)


async def test_an_update_to_a_shipped_workflow_waits_for_publish_review(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    old, new = shipped("purged"), shipped("purged_v2")
    await provision(engine, tenant, old)
    await provision(engine, tenant, new)
    await provision(engine, tenant, new)
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        live = await store.current(old["id"]) or {}
        asked = await AgentRegistry(engine).requests(KIND, old["id"])
        updated = await ServiceEvents(engine).get(UPDATED, f"{old['id']}:{parse(new).digest()[:16]}")
    assert (live["version"], live["digest"]) == (1, parse(old).digest()), live
    assert [(r["version"], r["status"], r["requested_by"]) for r in asked] == [(2, "pending", SEED)], asked
    assert updated is not None and updated["payload"]["status"] == "pending"


async def test_where_no_review_is_needed_the_update_goes_live(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    old, new = shipped("purged"), shipped("purged_v2")
    await provision(engine, tenant, old)
    await provision(engine, tenant, new, review={"": {"workflows": "never"}})
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        live = await store.current(old["id"]) or {}
    assert (live["version"], live["stage"], live["digest"]) == (2, "live", parse(new).digest()), live


async def test_a_tenant_that_published_its_own_version_keeps_it_and_is_told(engine: AsyncEngine) -> None:
    tenant = f"t-{uuid4().hex[:8]}"
    old, new = shipped("purged"), shipped("purged_v2")
    await provision(engine, tenant, old)
    store = DefinitionStore(EngineTransactions(engine))
    mine = parse(shipped("purged_by_us"))
    with tenant_scope(tenant):
        version, _ = await store.publish(
            mine.id, name="Ours", definition=mine.wire(), digest=mine.digest(), now=now_iso(), by="p@x"
        )
        await store.go_live(mine.id, version)
    await provision(engine, tenant, new)
    with tenant_scope(tenant):
        live = await store.current(old["id"]) or {}
        told = await ServiceEvents(engine).get(UPDATE_AVAILABLE, f"{old['id']}:{parse(new).digest()[:16]}")
    assert (live["version"], live["digest"]) == (version, mine.digest()), live
    assert told is not None and told["payload"]["liveVersion"] == version


async def test_a_tenant_on_the_platform_owned_version_follows_the_seed_too(engine: AsyncEngine) -> None:
    """A tenant provisioned while these were platform-owned system workflows (0a7ea469) has its live version published
    by "system": it is still the seed's own, so an update reaches it as a publish request, not a silent notice."""
    tenant = f"t-{uuid4().hex[:8]}"
    old, new = parse(shipped("purged")), shipped("purged_v2")
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(tenant):
        version, _ = await store.publish(
            old.id, name="Purge", definition=old.wire(), digest=old.digest(), now=now_iso(), by="system"
        )
        await store.go_live(old.id, version)
    await provision(engine, tenant, new)
    with tenant_scope(tenant):
        asked = await AgentRegistry(engine).requests(KIND, old.id)
    assert [(r["version"], r["status"]) for r in asked] == [(2, "pending")], asked
