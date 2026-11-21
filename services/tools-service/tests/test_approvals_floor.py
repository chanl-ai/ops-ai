"""The Security team's floor under every team's approval rules (`approvalsFloor`), as tools-service applies it at the
moment of a decision, by failure mode: a workspace that stored requesterMayDecide true before the floor was locked
letting an asker approve their own tool write; a team's looser appChanges, saved before the floor, letting a write
run unasked. platform-service is a fake here, answering GET /v1/policies/{key}."""

from __future__ import annotations

from typing import Any

import httpx

from ops_identity import ActingForPerson
from ops_tools.gateway_calls import ACCESS
from ops_tools.modules.policy import RequesterMayDecide, WriteApprovals, asker_refusal

from .service_clients import fake_service

DANA = ActingForPerson(sub="usr_dana", email="dana@bank.example", name="Dana", team_id="team_ops")


def platform(values: dict[str, Any]) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        key = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"success": True, "data": {"key": key, "value": values.get(key, {})}})

    return fake_service(handler, "platform", ["settings:view"])


async def test_a_locked_floor_refuses_the_askers_own_tool_write_approval_though_the_workspace_stored_true() -> None:
    stored = platform({"requesterMayDecide": True, "approvalsFloor": {"requesterMayDecide": False}})
    may_decide = await RequesterMayDecide(stored).allowed("t")
    refused = asker_refusal(ACCESS, DANA, "t", [DANA.email], may_decide=may_decide)
    assert refused is not None and refused.code == "own_request", (may_decide, refused)


async def test_a_looser_app_changes_value_saved_before_the_floor_waits_for_the_floor_at_decision_time() -> None:
    saved = platform({"appChanges": {"team_ops": {"ask": False}}, "approvalsFloor": {"appChanges": "reviewer"}})
    got = await WriteApprovals(saved).answer("t", "team_ops", None, access="write", setting=None)
    assert (got["waits"], got["answer"]) == (True, "reviewer"), got
