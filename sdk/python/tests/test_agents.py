"""Agent facade: validate names missing fields, apply posts a create body, chat opens a thread then streams."""

from __future__ import annotations

import json
from typing import Any

import httpx
from ops_ai import OpsAI
from ops_ai.cli import main

BASE = "https://ops.test"


def client(handler: Any) -> OpsAI:
    return OpsAI(
        api_key="ok_test",
        base_url=BASE,
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def ok(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"success": True, "data": data})


def sse(data: Any, event: str = "message") -> httpx.Response:
    return httpx.Response(
        200,
        content=f"event: {event}\ndata: {json.dumps(data)}\n\n",
        headers={"content-type": "text/event-stream"},
    )


def test_validate_refuses_an_agent_without_a_role() -> None:
    check = client(lambda _: ok({})).agents.validate({"name": "Guide"})
    assert check["ok"] is False
    assert check["checks"][0]["field"] == "role"


def test_apply_creates_and_chat_opens_a_thread() -> None:
    seen: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r.url.path)
        if r.url.path.endswith("/v1/agents") and r.method == "GET":
            return ok([])
        if r.url.path.endswith("/v1/agents") and r.method == "POST":
            body = json.loads(r.content)
            assert body["name"] == "Guide" and body["role"] == "answer"
            return ok({"id": "ag_1", "name": "Guide", "version": 1}, 201)
        if r.url.path.endswith("/v1/threads"):
            body = json.loads(r.content)
            assert body["graph"] == "agent:ag_1"
            return ok({"threadId": "th_1"}, 201)
        if "/runs/stream" in r.url.path:
            body = json.loads(r.content)
            assert body["input"]["message"]
            return sse({"reply": "Business accounts need two documents."})
        return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "message": r.url.path}})

    ops = client(handler)
    made = ops.agents.apply({"name": "Guide", "role": "answer", "instructions": "Answer from the prompt."})
    assert made["id"] == "ag_1"
    reply = ops.agents.chat("ag_1", "What documents open a business account?")
    assert "documents" in reply["reply"]
    assert reply["citations"] == []
    assert reply["toolCalls"] == []
    assert any(path.endswith("/v1/threads") for path in seen)


def test_apply_updates_an_existing_agent_by_name() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        if r.url.path.endswith("/v1/agents") and r.method == "GET":
            return ok([{"id": "ag_2", "name": "Policy advisor"}])
        if r.url.path.endswith("/v1/agents/ag_2") and r.method == "PATCH":
            body = json.loads(r.content)
            assert body["collections"] == ["kb_1"]
            return ok({"id": "ag_2", "name": "Policy advisor", "collections": ["kb_1"]})
        return httpx.Response(404, json={"success": False, "error": {"code": "not_found", "message": r.url.path}})

    made = client(handler).agents.apply({"name": "Policy advisor", "role": "answer", "collections": ["kb_1"]})
    assert made["id"] == "ag_2"
    assert made["collections"] == ["kb_1"]


def test_collect_chat_keeps_citations_and_tool_calls() -> None:
    events = [
        {"event": "tool_call", "data": {"name": "search_customers", "input": {"query": "ada@example.test"}}},
        {"event": "citation", "data": [{"source": "Account opening", "section": "Documents"}]},
        {"event": "message", "data": {"reply": "Ada Lovelace is a customer [1]."}},
    ]
    collected = __import__("ops_ai._agents", fromlist=["_collect_chat"])._collect_chat(events, "th_2")
    assert collected["reply"].startswith("Ada")
    assert collected["citations"][0]["source"] == "Account opening"
    assert collected["toolCalls"][0]["name"] == "search_customers"


def test_collect_chat_joins_graph_text_deltas_and_nested_citations() -> None:
    events = [
        {"data": {"event": "text", "runId": "run_1", "data": "A sole "}},
        {"data": {"event": "text", "runId": "run_1", "data": "proprietor brings [2]."}},
        {
            "data": {
                "event": "citation",
                "runId": "run_1",
                "data": [{"title": "Documents for a business chequing account", "n": 2}],
            }
        },
    ]
    collected = __import__("ops_ai._agents", fromlist=["_collect_chat"])._collect_chat(events, "th_3")
    assert collected["reply"] == "A sole proprietor brings [2]."
    assert collected["citations"][0]["title"] == "Documents for a business chequing account"


def test_cli_chat_prints_the_reply(monkeypatch: Any, capsys: Any) -> None:
    class Fake:
        agents = type(
            "A",
            (),
            {"chat": staticmethod(lambda _id, message: {"reply": f"Answered: {message}", "threadId": "th_1"})},
        )()

    monkeypatch.setattr("ops_ai._cli.agents.client", lambda ns: Fake())
    assert main(["agents", "chat", "ag_1", "--message", "What documents open a business account?"]) == 0
    assert "documents" in capsys.readouterr().out
