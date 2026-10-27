"""A run's tool calls carry its team (c-200): the worker's pass sets the run's team, so the service token a tool call
mints (`app.service_token_for`, `current_team()`) names it, as a person's request does. Failure mode: a worker pass
acts for no team, so tools-service cannot tell which team's mailbox a reply may leave from."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.worker import enter_run
from ops_agents.store.tenancy import current_team
from ops_engine.ports import ToolResult
from ops_engine.worker import Worker
from tests.engine.test_worker import (  # noqa: F401
    CountingTools,  # pyright: ignore[reportUnusedImport]
    drain,  # pyright: ignore[reportUnusedImport]
    engine,  # pyright: ignore[reportUnusedImport]
    start,  # pyright: ignore[reportUnusedImport]
    worker,  # pyright: ignore[reportUnusedImport]
)


class TeamTools(CountingTools):
    def __init__(self) -> None:
        super().__init__()
        self.teams: list[str | None] = []

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        self.teams.append(current_team())
        return await super().call(operation, input, key, generation, token)


async def test_a_runs_tool_call_acts_in_the_runs_team(engine: AsyncEngine) -> None:  # noqa: F811
    tools = TeamTools()
    w: Worker = worker(engine, tools, InMemorySaver())
    w.host.enter_run = enter_run
    await start(engine, f"t-{uuid4().hex[:8]}", {"customerId": "C-1", "amount": 250})
    await drain(w)
    assert tools.teams and set(tools.teams) == {"team_a"}
