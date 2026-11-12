"""Setting an agent up end to end, by failure mode against httpx's mock transport: an import that brings in more or
fewer operations than were ticked; a security decision sent for a version that waits on none; a grant that drops the
tools the agent already holds; and a held write approved without the step-up it asks for."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from ops_ai import AsyncOpsAI, OpsAI
from ops_ai.errors import BadRequest

SPEC = {
    "operations": [
        {"name": "get_account", "access": "read"},
        {"name": "get_statement", "access": "read"},
        {"name": "place_hold", "access": "write"},
    ]
}


def client(answer: Any, seen: list[httpx.Request]) -> OpsAI:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        status, data = answer(r)
        if status >= 400:
            return httpx.Response(status, json={"success": False, "error": data})
        return httpx.Response(status, json={"success": True, "data": data})

    return OpsAI(
        api_key="ok_test",
        base_url="https://ops.test",
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_a_module_is_made_empty_and_named_for_the_import() -> None:
    seen: list[httpx.Request] = []
    ops = client(lambda r: (200, {"id": "mod_1"}), seen)
    ops.tools.create_module("core_banking", "Core banking")
    assert seen[-1].url.path.endswith("/v1/tool-modules/blank")
    assert json.loads(seen[-1].content) == {"name": "core_banking", "displayName": "Core banking", "type": "openapi"}


def test_import_brings_in_exactly_the_ticked_operations_and_refuses_a_name_the_document_lacks() -> None:
    seen: list[httpx.Request] = []
    ops = client(lambda r: (200, SPEC if r.url.path.endswith("/discover") else {"id": "mod_1"}), seen)
    ops.tools.import_openapi("mod_1", "https://api.bank.test/openapi.json", ["get_account", "place_hold"])
    sent = json.loads(seen[-1].content)
    assert [o["name"] for o in sent["operations"]] == ["get_account", "place_hold"]
    assert sent["source"] == {"kind": "openapi", "specUrl": "https://api.bank.test/openapi.json"}
    with pytest.raises(ValueError, match="place_holds"):
        ops.tools.import_openapi("mod_1", "https://api.bank.test/openapi.json", ["place_holds"])


def test_a_review_decision_goes_to_the_review_the_version_waits_on() -> None:
    seen: list[httpx.Request] = []
    waiting = {"id": "mod_1", "versions": [{"status": "published"}, {"status": "in_review", "reviewId": "rev_9"}]}
    ops = client(lambda r: (200, {"status": "approved"}), seen)
    review = ops.tools.review_of(waiting)
    ops.tools.decide_review(review, "approved", reason="reads only")
    assert seen[-1].url.path.endswith("/v1/publish-requests/rev_9/decision")
    assert json.loads(seen[-1].content) == {"decision": "approved", "reason": "reads only"}
    with pytest.raises(ValueError, match="request one first"):
        ops.tools.review_of({"id": "mod_1", "versions": [{"status": "published"}]})


def test_granting_tools_keeps_the_ones_the_agent_already_holds() -> None:
    seen: list[httpx.Request] = []
    ops = client(lambda r: (200, {"id": "agt_1", "toolIds": ["op:a", "op:b"]}), seen)
    ops.agents.grant_tools("agt_1", ["op:b", "op:c"])
    assert json.loads(seen[-1].content) == {"toolIds": ["op:a", "op:b", "op:c"]}


def test_a_held_write_asks_for_the_step_up_and_is_retried_once_with_its_token() -> None:
    seen: list[httpx.Request] = []

    def answer(r: httpx.Request) -> tuple[int, Any]:
        if r.url.path.endswith("/step-up"):
            return 200, {"token": "su_1"}
        if "stepUpToken" in json.loads(r.content or b"{}"):
            return 200, {"decided": "approve"}
        return 400, {"code": "step_up_required", "message": "confirm it is you"}

    ops = client(answer, seen)
    assert ops.tasks.approve("thr_1", password="pw") == {"decided": "approve"}
    assert json.loads(seen[-1].content)["stepUpToken"] == "su_1"
    with pytest.raises(BadRequest):
        ops.tasks.approve("thr_1")


def test_the_async_client_makes_the_step_up_and_retries_the_held_write() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/step-up"):
            return httpx.Response(200, json={"success": True, "data": {"token": "su_1"}})
        if "stepUpToken" in json.loads(r.content or b"{}"):
            return httpx.Response(200, json={"success": True, "data": {"decided": "approve"}})
        return httpx.Response(400, json={"success": False, "error": {"code": "step_up_required", "message": "confirm"}})

    async def run() -> Any:
        async with AsyncOpsAI(
            api_key="ok_test",
            base_url="https://ops.test",
            team="team_a",
            http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        ) as ops:
            return await ops.tasks.approve("thr_1", password="pw")

    assert asyncio.run(run()) == {"decided": "approve"}
