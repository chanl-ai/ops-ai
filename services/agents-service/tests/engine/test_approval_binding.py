"""The approval token a reviewed write carries names its run's workflow and whether that run is the tenant's handler for
a service event (`system`, c-258): the no-team workflow under a shipped event workflow's id. The gateway runs a
platform tool only for the handler that owns the decision. Failure mode: a team workflow's own review step, under the
handler's id or another, mints a token the gateway takes for the handler's."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.api.engine_host import ApprovalMinter
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.reviews import ReviewStore
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore, RunStore
from ops_policy import input_hash
from ops_policy.approval import binding_of
from ops_service_kit.ids import new_id
from tests.engine.test_not_decided_by import FLOW

KEY = "k" * 40


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(database_url)
    yield e
    await e.dispose()


async def token_for(engine: AsyncEngine, tenant: str, wid: str, *, team: str | None) -> str:
    tx = EngineTransactions(engine)
    with tenant_scope(tenant):
        version, _ = await DefinitionStore(tx).publish(
            wid,
            name=wid,
            definition=FLOW.wire() | {"id": wid},
            digest=wid.ljust(64, "d"),
            now="n",
            by="s",
            team=team,
            stage="live",
        )
        run_id = new_id("wfrun")
        base = {"id": run_id, "team_id": "team_a", "workflow_id": wid, "version": version, "digest": wid.ljust(64, "d")}
        await RunStore(tx).create(base | {"run_key": run_id, "mode": "live", "input": {}, "created_by": "a@x"})
        call: dict[str, Any] = {"step": "s1", "tool": "apply_tool_access_approved", "input": {"module": "m"}}
        approval = {"approvers": ["r@x"], "step": "s1", "inputHash": input_hash(call["input"])}
        token = await ApprovalMinter(engine, KEY, 60).mint(run_id, call, approval)
    assert token is not None
    return token


async def test_the_token_says_which_workflow_and_whether_it_is_the_events_handler(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def approved(_self: Any, _run: str, _step: str, _digest: str) -> list[tuple[str, str]]:
        return [("r@x", "approved")]

    monkeypatch.setattr(ReviewStore, "approvals_of_input", approved)

    async def bound(wid: str, team: str | None) -> tuple[str, bool]:
        b = binding_of(await token_for(engine, f"t-{uuid4().hex[:8]}", wid, team=team), KEY)
        return b.workflow, b.system

    assert await bound("tool_access_request", None) == ("tool_access_request", True)
    assert await bound("tool_access_request", "team_a") == ("tool_access_request", False), "a team's copy of its id"
    assert await bound("team_lookalike", None) == ("team_lookalike", False), "a shared workflow that handles no event"
