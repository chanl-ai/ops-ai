"""What a guardrail took back from a person stays on the record (tick 28), by failure mode: text that streamed and was
then withdrawn is lost from the journal, so the audit cannot say what the person saw; the record does not survive a
reload; or it reaches a reader the roles grid does not let view the audit. Tokens carry real roles, as
platform-service mints them: an admin may view the audit, a builder may not."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from tests.conftest import sse_events, structured
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER

from .role_app import ok, role_app

ADVISOR = "ag_branch"
RULE = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't give investment advice."}
ANSWER = "Buy Harbor & Pine shares before Friday."


def _withdrawing_model() -> FunctionModel:
    """Answers with investment advice, which the after-answer check then finds; the question itself is clean."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        prompt = (
            " ".join(str(p.content) for p in last.parts if isinstance(p, UserPromptPart))
            if isinstance(last, ModelRequest)
            else ""
        )
        if prompt.startswith("<remember>"):
            return structured(info, {"memories": []})
        if prompt.startswith("Blocked topics:"):
            topic = "investment advice" if "shares" in prompt else "none"
            return ModelResponse(parts=[ToolCallPart("final_result", {"topic": topic, "reason": "test"})])
        return ModelResponse(parts=[TextPart(ANSWER)])

    async def stream(messages: list[ModelMessage], info: AgentInfo) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
        for part in respond(messages, info).parts:
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

    return FunctionModel(respond, stream_function=stream)


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with role_app(_withdrawing_model()) as c:
        yield c


async def _guarded(c: AsyncClient) -> None:
    g = ok(await c.post("/v1/guardrails", json=RULE, headers=ADMIN), 201)
    ok(await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=ADMIN), 201)
    pin = {"guardrailPins": [{"guardrailId": g["id"], "version": 1}]}
    agent = ok(await c.patch(f"/v1/agents/{ADVISOR}", json=pin, headers=ADMIN))
    ok(await c.post(f"/v1/agents/{ADVISOR}/publish-requests", json={"version": agent["version"]}, headers=ADMIN), 201)


async def _ask(c: AsyncClient, who: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    tid = ok(await c.post("/chat/threads", json={"agentId": ADVISOR, "kbIds": []}, headers=who), 201)["id"]
    res = await c.post(
        f"/chat/threads/{tid}/messages",
        json={"content": "What should I tell my client?"},
        headers={**who, "Accept": "text/event-stream"},
    )
    assert res.status_code == 200, res.text
    return tid, sse_events(res.text)


async def test_withdrawn_text_is_kept_for_the_audit_and_survives_a_reload(client: AsyncClient) -> None:
    await _guarded(client)
    tid, events = await _ask(client, ADMIN)
    # It streamed, then was replaced: the person saw the answer before the check took it back.
    assert ANSWER in "".join(e.get("delta", "") for e in events if e.get("type") == "text"), events
    assert any(e.get("type") == "replace" for e in events), events
    reloaded = ok(await client.get(f"/chat/threads/{tid}", headers=ADMIN))["messages"][-1]
    assert reloaded["content"] == RULE["message"]
    [entry] = reloaded["guardrailAudit"]
    assert (entry["kind"], entry["text"]) == ("retracted", ANSWER), entry
    assert (entry["guardrail"]["name"], entry["guardrail"]["topic"]) == (RULE["name"], "investment advice")
    assert entry["at"], entry


async def test_a_reader_who_may_not_view_the_audit_never_gets_the_withdrawn_text(client: AsyncClient) -> None:
    await _guarded(client)
    tid, events = await _ask(client, BUILDER)
    reloaded = ok(await client.get(f"/chat/threads/{tid}", headers=BUILDER))
    assert reloaded["messages"][-1]["content"] == RULE["message"]
    assert ANSWER not in json.dumps(reloaded) and "guardrailAudit" not in json.dumps(reloaded), reloaded
    # The stream never carries the record either: it is written to the journal only.
    assert not any("guardrailAudit" in json.dumps(e) for e in events)
