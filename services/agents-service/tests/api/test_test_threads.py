"""A builder's test of an agent is a real chat thread the server marks test (c-284), by failure mode: a person marks
their own chat test to escape counts and memory; a test answers on the published version instead of the draft being
tested; a draft edited between two test messages is served stale; a test remembers things about the builder; test
threads inflate the agent's tasks or crowd the conversations list; the mark changes after the thread starts. Tokens
carry real roles: a builder may test the agent (agents.edit), a viewer may only chat."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, DeltaToolCall, FunctionModel

from tests.conftest import sse_events, structured
from tests.engine.test_lifecycle_rights import BUILDER, VIEWER

from .role_app import ok, role_app

ADVISOR = "ag_branch"


class Recorder:
    """Answers with the marker it finds in the agent's instructions, so a reply says which version ran, and counts the
    memory extractions it is asked for."""

    def __init__(self) -> None:
        self.extractions = 0

    def model(self) -> FunctionModel:
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            first, last = messages[0], messages[-1]
            prompt = (
                " ".join(str(p.content) for p in last.parts if isinstance(p, UserPromptPart))
                if isinstance(last, ModelRequest)
                else ""
            )
            if prompt.startswith("<remember>"):
                self.extractions += 1
                return structured(info, {"memories": []})
            system = " ".join(
                [str(p.content) for p in first.parts if isinstance(p, SystemPromptPart)]
                + [str(getattr(m, "instructions", "") or "") for m in messages]
            )
            marks = [w for w in system.split() if w.startswith("MARK-")]
            return ModelResponse(parts=[TextPart(f"ran {marks[-1] if marks else 'published'}")])

        async def stream(
            messages: list[ModelMessage], info: AgentInfo
        ) -> AsyncIterator[str | dict[int, DeltaToolCall]]:
            for part in respond(messages, info).parts:
                if isinstance(part, TextPart):
                    yield part.content
                elif isinstance(part, ToolCallPart):
                    yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args))}

        return FunctionModel(respond, stream_function=stream)


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, Recorder]]:
    recorder = Recorder()
    async with role_app(recorder.model()) as c:
        yield c, recorder


async def _thread(c: AsyncClient, who: dict[str, str], *, test: bool) -> Any:
    return await c.post("/chat/threads", json={"agentId": ADVISOR, "kbIds": [], "test": test}, headers=who)


async def _say(c: AsyncClient, who: dict[str, str], tid: str, text: str = "Hello") -> str:
    res = await c.post(
        f"/chat/threads/{tid}/messages", json={"content": text}, headers={**who, "Accept": "text/event-stream"}
    )
    assert res.status_code == 200, res.text
    done = [e for e in sse_events(res.text) if e.get("type") in ("done", "error")]
    assert done and done[-1]["type"] == "done", done
    return str(done[-1]["message"]["content"])


async def _draft(c: AsyncClient, mark: str) -> None:
    """Edits the agent's instructions without publishing: the new version is a draft."""
    agent = ok(await c.get(f"/v1/agents/{ADVISOR}", headers=BUILDER))
    ok(
        await c.patch(
            f"/v1/agents/{ADVISOR}", json={"instructions": f"{agent['instructions']} {mark}"}, headers=BUILDER
        )
    )


async def test_a_test_thread_needs_the_right_to_test(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack
    refused = await _thread(c, VIEWER, test=True)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "role_required", refused.text
    assert ok(await c.get("/chat/threads", params={"test": "true"}, headers=VIEWER))["data"] == []
    made = ok(await _thread(c, BUILDER, test=True), 201)
    assert made["test"] is True
    # A viewer may still chat with the published agent; the thread is not a test.
    assert ok(await _thread(c, VIEWER, test=False), 201)["test"] is False


async def test_a_test_message_runs_the_newest_draft(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack
    await _draft(c, "MARK-DRAFT1")
    test = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    chat = ok(await _thread(c, BUILDER, test=False), 201)["id"]
    assert await _say(c, BUILDER, test) == "ran MARK-DRAFT1"
    assert await _say(c, BUILDER, chat) == "ran published"


async def test_an_edit_between_test_messages_is_what_the_next_one_runs(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack
    await _draft(c, "MARK-ONE")
    tid = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    assert await _say(c, BUILDER, tid) == "ran MARK-ONE"
    await _draft(c, "MARK-TWO")
    assert await _say(c, BUILDER, tid, "Again") == "ran MARK-TWO"


async def test_a_test_thread_remembers_nothing(stack: tuple[AsyncClient, Recorder]) -> None:
    c, recorder = stack
    await _say(c, BUILDER, ok(await _thread(c, BUILDER, test=False), 201)["id"], "I prefer to hear back by email.")
    assert recorder.extractions == 1
    await _say(c, BUILDER, ok(await _thread(c, BUILDER, test=True), 201)["id"], "I prefer to hear back by email.")
    assert recorder.extractions == 1


async def test_test_threads_are_left_out_of_counts(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack

    async def tasks() -> int:
        listed = ok(await c.get("/v1/agents", params={"pageSize": 100}, headers=BUILDER))["data"]
        return int(next(a for a in listed if a["id"] == ADVISOR)["tasks24h"])

    before = await tasks()
    await _say(c, BUILDER, ok(await _thread(c, BUILDER, test=True), 201)["id"])
    assert await tasks() == before
    await _say(c, BUILDER, ok(await _thread(c, BUILDER, test=False), 201)["id"])
    assert await tasks() == before + 1


async def test_the_list_leaves_test_threads_out_unless_asked(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack
    test = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    chat = ok(await _thread(c, BUILDER, test=False), 201)["id"]
    plain = ok(await c.get("/chat/threads", headers=BUILDER))
    tests = ok(await c.get("/chat/threads", params={"test": "true"}, headers=BUILDER))
    assert [t["id"] for t in plain["data"]] == [chat] and plain["data"][0]["test"] is False
    assert [t["id"] for t in tests["data"]] == [test] and tests["data"][0]["test"] is True


async def test_the_test_mark_cannot_be_patched(stack: tuple[AsyncClient, Recorder]) -> None:
    c, _ = stack
    test = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    chat = ok(await _thread(c, VIEWER, test=False), 201)["id"]
    for tid, who, value in ((test, BUILDER, False), (chat, VIEWER, True)):
        res = await c.patch(f"/chat/threads/{tid}", json={"test": value}, headers=who)
        assert res.status_code in (400, 422), res.text
    assert ok(await c.get(f"/chat/threads/{test}", headers=BUILDER))["test"] is True
    assert ok(await c.get(f"/chat/threads/{chat}", headers=VIEWER))["test"] is False


async def test_a_test_reply_says_what_it_spent(stack: tuple[AsyncClient, Recorder]) -> None:
    """c-286: each reply carries its model calls, tokens, cost and seconds, read with the thread (no second request)."""
    c, _ = stack
    await _draft(c, "MARK-COST")
    tid = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    await _say(c, BUILDER, tid)
    thread = ok(await c.get(f"/chat/threads/{tid}", headers=BUILDER))
    [reply] = [m for m in thread["messages"] if m["role"] == "assistant"]
    usage = reply["usage"]
    assert usage["calls"] >= 1 and usage["inputTokens"] > 0 and usage["outputTokens"] > 0, usage
    assert isinstance(usage["cost"], str) and isinstance(usage["seconds"], float), usage


async def test_a_compare_runs_the_same_question_on_two_versions(stack: tuple[AsyncClient, Recorder]) -> None:
    """c-286: a test thread started on a saved version runs that version, so the draft and the published answer can
    be read side by side; a version the agent does not have is refused."""
    c, _ = stack
    await _draft(c, "MARK-NEW")
    published = ok(await c.get(f"/v1/agents/{ADVISOR}", headers=BUILDER))["publishedVersion"]
    body: dict[str, Any] = {"agentId": ADVISOR, "kbIds": [], "test": True, "testVersion": published}
    old = ok(await c.post("/chat/threads", json=body, headers=BUILDER), 201)["id"]
    new = ok(await _thread(c, BUILDER, test=True), 201)["id"]
    assert (await _say(c, BUILDER, old), await _say(c, BUILDER, new)) == ("ran published", "ran MARK-NEW")
    missing = await c.post("/chat/threads", json={**body, "testVersion": 999}, headers=BUILDER)
    assert missing.status_code == 422, missing.text
