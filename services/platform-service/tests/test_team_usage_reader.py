"""What platform reads from agents-service's team usage reply before a team is deleted or a workspace closed."""

from __future__ import annotations

import json

import httpx
import pytest

from ops_identity import ServiceClient, dev_service_signer
from ops_platform.team_usage import AgentsUsage, TeamUsage, UsageUnavailable


def _reader(status: int, body: object) -> AgentsUsage:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/teams/usage"
        return httpx.Response(status, content=json.dumps(body).encode(), headers={"content-type": "application/json"})

    http = httpx.AsyncClient(base_url="http://agents", transport=httpx.MockTransport(answer))
    return AgentsUsage(ServiceClient(http, dev_service_signer(), "platform", "agents"))


@pytest.mark.parametrize(
    ("body", "usage"),
    [
        ({"runsInProgress": 2, "liveWorkflows": ["wf_a", 7]}, TeamUsage(2, ["wf_a", "7"])),
        ({}, TeamUsage(0, [])),
        ({"runsInProgress": None, "liveWorkflows": None, "other": 1}, TeamUsage(0, [])),
    ],
)
async def test_the_reply_is_read_as_runs_and_live_workflows(body: object, usage: TeamUsage) -> None:
    assert await _reader(200, body).of("ten_a", "team_a") == usage


async def test_an_error_answer_refuses_the_read() -> None:
    with pytest.raises(UsageUnavailable):
        await _reader(503, {"error": {"code": "unavailable"}}).of("ten_a", "team_a")
