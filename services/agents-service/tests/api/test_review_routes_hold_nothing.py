"""The review routes and the Overview ask tools-service for each held write's policy (`tool_access.policy_of`), and
a decision resumes the run. By failure mode: a route that took the request transaction would hold a database
connection while tools-service answers, so a slow tools-service would drain the pool for every other request."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.pool import QueuePool

from ops_agents.api import tool_access
from ops_agents.api.deps import Runtime
from ops_agents.api.tool_access import WritePolicy

from .test_hitl_facade import (  # noqa: F401  # a fixture
    paused_dispute,
    stack,  # pyright: ignore[reportUnusedImport]
)


async def test_no_connection_is_held_while_tools_service_answers_a_review_route(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rt = stack
    tid = await paused_dispute(client)
    held: list[int] = []

    async def watched(_rt: Any, _tool: str) -> WritePolicy:
        pool = rt.db.pool
        assert isinstance(pool, QueuePool)
        held.append(pool.checkedout())
        return WritePolicy("write", 1)

    monkeypatch.setattr(tool_access, "_policy_of", watched)
    seen = [
        (await client.get(f"/reviews/{tid}")).status_code,
        (await client.get("/reviews?view=open&page=1&pageSize=25")).status_code,
        (await client.get("/v1/overview")).status_code,
        (await client.post(f"/reviews/{tid}/decision", json={"decision": "approved"})).status_code,
    ]
    assert seen == [200, 200, 200, 200]
    assert held and set(held) == {0}, held
