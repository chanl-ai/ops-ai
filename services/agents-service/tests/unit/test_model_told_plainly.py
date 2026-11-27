"""What the model is told after a tool call, by failure mode: a result the person already sees as a table is shown a
second time when the model presents the same rows, costing a model call; and a refusal the chat draws as a Connect
card reaches the model with its code, link and address, which the model then pastes into its answer."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from ops_agent_kernel.contract import ModelEndpoint
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.testing import Answer, Reply, ToolCall, trailing_tool_results
from ops_agent_kernel.types import ToolGrant, TurnRequest
from ops_agents.activities.gateway import GatewayToolExecutor
from ops_agents.activities.shaper import shape_part
from ops_service_kit.http import Json
from ops_service_kit.narrow import json_object
from tests.conftest import model_on
from tests.unit.test_kernel import SETTINGS, FixedKnowledge, run

QUERY = ToolGrant("salesforce_query", "Salesforce", "Run a SOQL query", "read", {"type": "object", "properties": {}})
RECORDS = [{"Id": "5003000000D8cuJAAR", "CaseNumber": "00044818", "Status": "New"}]
ENVELOPE = {"totalSize": 1, "done": True, "records": RECORDS}
NOT_LINKED = {
    "error": {
        "code": "CONNECTION_NOT_LINKED",
        "message": "Salesforce needs james@harborpine.example to connect their own account.",
        "details": {
            "connectionId": "ca_1",
            "connection": "Salesforce",
            "reason": "not_connected",
            "connectUrl": "http://localhost:3016/connections/connect?link=abc",
        },
    }
}


def model(steps: Sequence[Answer], seen: list[Any]) -> ModelEndpoint:
    """Answers each model call with the next step; records every tool result it was given."""

    def script(messages: list[Json], tools: list[Json]) -> Answer:
        seen.extend(trailing_tool_results(messages))
        return steps[min(len(seen), len(steps) - 1)]

    return model_on(script)


class Drawn:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        return ToolOutcome(True, ENVELOPE, {"part": shape_part(ENVELOPE, part_id="")})


class Gateway:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def call(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> dict[str, Any]:
        return self.data


async def test_rows_a_tool_already_drew_are_not_presented_again() -> None:
    seen: list[Any] = []
    steps = [
        Reply(tool_calls=[ToolCall("salesforce_query", {})]),
        Reply(tool_calls=[ToolCall("present", {"shape": "rows", "data": RECORDS})]),
        "Case 00044818 is New.",
    ]
    req = TurnRequest("t1", "th1", SETTINGS, [QUERY], user_turn="status of case 00044818")
    _, result = await run(req, KernelPorts(model=model(steps, seen), tools=Drawn(), knowledge=FixedKnowledge([])))
    parts = [json_object(r.view["part"]) for r in result.tool_calls if r.view]
    assert len(parts) == 1 and parts[0]["shape"] == "rows", parts
    assert "present" in json.dumps(seen[0]) and "above or below" in json.dumps(seen[0]), seen[0]


async def test_a_record_read_after_a_query_that_drew_it_is_not_drawn_again() -> None:
    seen: list[Any] = []
    get = ToolGrant("salesforce_get_record", "Salesforce", "Get a record", "read", {"type": "object", "properties": {}})

    class QueryThenRead:
        async def execute(
            self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
        ) -> ToolOutcome:
            out: Any = ENVELOPE if tool == "salesforce_query" else RECORDS[0]
            return ToolOutcome(True, out, {"part": shape_part(out, part_id="")})

    steps = [
        Reply(tool_calls=[ToolCall("salesforce_query", {})]),
        Reply(tool_calls=[ToolCall("salesforce_get_record", {})]),
        "Case 00044818 is New.",
    ]
    req = TurnRequest("t1", "th1", SETTINGS, [QUERY, get], user_turn="status of case 00044818")
    tools = QueryThenRead()
    _, result = await run(req, KernelPorts(model=model(steps, seen), tools=tools, knowledge=FixedKnowledge([])))
    assert [r.tool for r in result.tool_calls if r.view] == ["salesforce_query"], result.tool_calls


async def test_a_connect_card_refusal_reaches_the_model_as_a_plain_line() -> None:
    seen: list[Any] = []
    steps = [Reply(tool_calls=[ToolCall("salesforce_query", {})]), "Connect."]
    tools = GatewayToolExecutor(Gateway({"ok": False, "output": NOT_LINKED}), None)  # type: ignore[arg-type]
    req = TurnRequest("t1", "th1", SETTINGS, [QUERY], user_turn="status of case 00044818")
    _, result = await run(req, KernelPorts(model=model(steps, seen), tools=tools, knowledge=FixedKnowledge([])))
    told = json.dumps(seen[0])
    # The model says the ask carries on once they connect, never that they should ask again.
    assert "carry on with this ask once they sign in" in told and "ask again" not in told, told
    assert "offer no other steps" in told and "Salesforce" in told, told
    assert not any(s in told for s in ("CONNECTION_NOT_LINKED", "http", "@", "connectUrl")), told
    # The card still reads the whole refusal from the call record.
    assert result.tool_calls[0].output == NOT_LINKED
