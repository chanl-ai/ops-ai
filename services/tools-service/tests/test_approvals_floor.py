"""The Security team's floor under every team's approval rules (`approvalsFloor`), as tools-service applies it at the
moment of a decision, by failure mode: a team's looser appChanges, saved before the floor, letting a write run unasked.
platform-service is a fake here, answering GET /v1/policies/{key}. Who approves their own request is the Approvals
decide cell, asked live (test_apply_tool_access.py)."""

from __future__ import annotations

from typing import Any

import httpx

from ops_tools.modules.policy import WriteApprovals

from .service_clients import fake_service


def platform(values: dict[str, Any], *, unserved: str | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        if key == unserved:
            return httpx.Response(503, json={"success": False, "error": {"code": "unavailable", "message": "down"}})
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": values.get(key, {})}})

    return fake_service(handler, "platform", ["settings:view"])


async def test_a_looser_app_changes_value_saved_before_the_floor_waits_for_the_floor_at_decision_time() -> None:
    saved = platform({"appChanges": {"team_ops": {"ask": False}}, "approvalsFloor": {"appChanges": "reviewer"}})
    got = await WriteApprovals(saved).answer("t", "team_ops", None, access="write", setting=None)
    assert (got["waits"], got["answer"]) == (True, "reviewer"), got


async def test_a_floor_that_is_not_served_makes_every_write_wait_for_a_reviewer() -> None:
    values = {"appChanges": {"team_ops": {"ask": False}}}
    down = platform(values, unserved="approvalsFloor")
    got = await WriteApprovals(down).answer("t", "team_ops", None, access="write", setting=None)
    assert (got["waits"], got["answer"]) == (True, "reviewer"), got
