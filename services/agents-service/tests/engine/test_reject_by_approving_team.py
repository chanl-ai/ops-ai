"""A workflow review that holds a write is decided, approve or reject, by whoever may approve that write: the
operation's approving team when its policy names one, which the review names. On PostgreSQL with the real worker;
failure mode (the Chat and agents showcase run): a reviewer refused the approval rejects the same write."""

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
        return {"team_fraud": "Fraud Operations"}.get(team_id)


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


async def test_a_reviewer_outside_the_writes_approving_team_cannot_reject_it(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fraud_decides(_rt: Any, _tool: str) -> WritePolicy:
        return WritePolicy("write", 1, "team_fraud")

    monkeypatch.setattr(engine_reviews, "policy_of", fraud_decides)
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
    assert shown["decidingTeam"] == {"id": "team_fraud", "name": "Fraud Operations"}, shown
    # Maya reviews for the run's team, not for Fraud.
    with tenant_scope(tenant), pytest.raises(Forbidden) as refused:
        await engine_reviews.decide(rt, reviewer("maya@x", "team_a"), run_id, decision="rejected", reason="Not ours")
    assert refused.value.code == "role_required", refused.value
    with tenant_scope(tenant):
        await engine_reviews.decide(
            rt, reviewer("nadia@x", "team_a", "team_fraud"), run_id, decision="rejected", reason="Not ours"
        )
    await drain(w)
    with tenant_scope(tenant):
        assert ((await RunStore(EngineTransactions(engine)).get(run_id)) or {}).get("outcome") == "rejected"
