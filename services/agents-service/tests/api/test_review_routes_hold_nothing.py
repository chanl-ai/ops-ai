"""The review routes and the Overview ask tools-service for each held write's policy (`tool_access.policy_of`), and
a decision resumes the run. By failure mode: a route that took the request transaction would hold a database
connection while tools-service answers, so a slow tools-service would drain the pool for every other request."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import QueuePool

from ops_agents.api import tool_access
from ops_agents.api.deps import Runtime
from ops_agents.api.review_sla import PlatformReviewSla
from ops_agents.api.team_names import PlatformTeamNames
from ops_agents.api.tool_access import WritePolicy
from ops_identity import ServiceUnreachable
from tests.engine.test_lifecycle_rights import BUILDER

from .test_case_page import _waiting_on, typed_case  # pyright: ignore[reportPrivateUsage]
from .test_hitl_facade import (  # noqa: F401  # a fixture
    paused_dispute,
    stack,  # pyright: ignore[reportUnusedImport]
)
from .test_team_default_agent import Stack  # pyright: ignore[reportUnusedImport]
from .test_team_default_agent import stack as case_stack  # noqa: F401  # pyright: ignore[reportUnusedImport]


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


class WatchedPlatform:
    """Stands in for platform-service: records whether a transaction was open at each question, then fails, or answers
    with a team list that lacks the team asked about (a deleted team)."""

    def __init__(self, mode: str, engine: Any) -> None:
        self.mode, self.open = mode, 0
        self.asked: list[tuple[str, int]] = []
        for name, step in (("begin", 1), ("commit", -1), ("rollback", -1)):
            event.listen(engine, name, self.counting(step))

    def counting(self, step: int) -> Callable[[object], None]:
        def count(_conn: object) -> None:
            self.open += step

        return count

    async def get(self, path: str, params: Any = None) -> Any:
        self.asked.append((path, self.open))
        if self.mode == "down":
            raise ServiceUnreachable("platform-service is down")
        return [] if path == "/v1/team-names" else {}


@pytest.mark.parametrize("mode", ["down", "missing"])
async def test_no_transaction_is_open_when_platform_service_is_asked_by_a_review_route(
    mode: str,
    case_stack: Stack,  # noqa: F811
) -> None:
    c, rt = case_stack
    case_id = await typed_case(case_stack, customer="C-platform")
    await _waiting_on(case_stack, case_id, 1)
    platform = WatchedPlatform(mode, rt.db.sync_engine)
    rt.team_names, rt.review_sla = PlatformTeamNames(platform), PlatformReviewSla(platform)  # type: ignore[arg-type]
    listed = await c.get("/reviews", headers=BUILDER)
    review_id = listed.json()["data"]["data"][0]["id"]
    seen = {
        "/reviews": listed.status_code,
        "/v1/overview": (await c.get("/v1/overview", headers=BUILDER)).status_code,
        f"/reviews/{review_id}": (await c.get(f"/reviews/{review_id}", headers=BUILDER)).status_code,
        f"/v1/cases/{case_id}": (await c.get(f"/v1/cases/{case_id}", headers=BUILDER)).status_code,
    }
    assert set(seen.values()) == {200}, seen
    assert platform.asked, "platform-service was never asked"
    assert [a for a in platform.asked if a[1]] == [], platform.asked
