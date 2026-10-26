"""A workflow review that holds a write is decided, approve or reject, in the run's own team, even when the tool's
policy names another team. On PostgreSQL with the real worker; failure mode: a reviewer from the tool's team, who
cannot see the run, rejects it, or the run's own reviewer is refused."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api import engine_reviews
from ops_agents.api.auth import Principal
from ops_agents.api.tool_access import WritePolicy
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.definition import parse
from ops_engine.store import RunStore
from ops_service_kit.errors import Forbidden
from tests.engine.review_flows import paused
from tests.engine.test_worker import drain

WRITE = parse(
    {
        "schemaVersion": 2,
        "id": "case_note",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {
                "id": "review",
                "type": "ops.flow.humanReview",
                "typeVersion": 1,
                "parameters": {"title": "Write the note", "approves": "note"},
            },
            {
                "id": "note",
                "type": "ops.action.tool",
                "typeVersion": 1,
                "parameters": {
                    "operation": "add_customer_note",
                    "input": {"text": "$.input.name"},
                    "approvedBy": "review",
                },
            },
            {"id": "ok", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "approved"}},
            {"id": "no", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "rejected"}},
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "note", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "no", "port": "in"}},
            {"from": {"node": "note", "port": "ok"}, "to": {"node": "ok", "port": "in"}},
        ],
    }
)


def _no_card(_name: str) -> None:
    return None


class _NoTools:
    async def operations(self) -> list[Any]:
        return []


class _Names:
    async def name(self, team_id: str) -> str | None:
        return {"team_a": "Card Disputes", "team_fraud": "Fraud Operations"}.get(team_id)


def reviewer(email: str, *teams: str) -> Principal:
    return Principal(
        name=email,
        email=email,
        team_id=teams[0],
        tenant_id="local",
        team_ids=teams,
        roles=dict.fromkeys(teams, "approver"),
    )


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def test_a_held_write_is_rejected_in_its_runs_team(engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch) -> None:
    async def one_approver(_rt: Any, _tool: str) -> WritePolicy:
        return WritePolicy("write", 1)

    monkeypatch.setattr(engine_reviews, "policy_of", one_approver)
    tenant, run_id, rt, w = await paused(engine, WRITE)
    # What the review's words read: no catalog card and no directory, so the call is described from its input alone.
    rt.catalog, rt.directory = SimpleNamespace(tool=_no_card), _NoTools
    rt.team_names = _Names()
    with tenant_scope(tenant):
        run: dict[str, Any] = await RunStore(EngineTransactions(engine)).get(run_id) or {}
    held: dict[str, Any] = dict(run.get("waiting") or {}).get("payload") or {}
    assert held.get("call"), held
    with tenant_scope(tenant):
        shown = await engine_reviews.get(rt, run_id)
    assert shown["decidingTeam"] == {"id": "team_a", "name": "Card Disputes"}, shown
    # Nadia approves for Fraud, the tool's team, and cannot see or decide this run.
    with tenant_scope(tenant), pytest.raises(Forbidden):
        await engine_reviews.decide(
            rt, reviewer("nadia@x", "team_fraud"), run_id, decision="rejected", reason="Not ours"
        )
    with tenant_scope(tenant):
        await engine_reviews.decide(rt, reviewer("maya@x", "team_a"), run_id, decision="rejected", reason="Not ours")
    await drain(w)
    with tenant_scope(tenant):
        assert ((await RunStore(EngineTransactions(engine)).get(run_id)) or {}).get("outcome") == "rejected"
