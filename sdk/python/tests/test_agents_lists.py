"""The agents lists by failure mode: a list that stops after its first page, a page size above the maximum, a renamed
query key sent under its old name, a batch body that carries a field the API refuses, and an inbox refused to a
teammate."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from ops_ai import NotFound, OpsAI

BASE = "https://ops.test"


def client(handler: Any) -> OpsAI:
    return OpsAI(api_key="ok", base_url=BASE, team="t", http=httpx.Client(transport=httpx.MockTransport(handler)))


def three_pages(seen: list[httpx.Request]) -> Any:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        page = int(r.url.params.get("page", "1"))
        body = {"data": [f"row{page}"], "pagination": {"page": page, "hasNext": page < 3}, "facets": {}}
        return httpx.Response(200, json={"success": True, "data": body})

    return handler


LISTS = [
    ("/v1/agents", lambda c: c.agents.list(search="x")),
    ("/v1/skills", lambda c: c.skills.list(ids=["s1"])),
    ("/v1/guardrails", lambda c: c.guardrails.list(search="x")),
    ("/v1/widgets", lambda c: c.widgets.list(search="x")),
    ("/v1/case-types", lambda c: c.case_types.list(search="x")),
    ("/v1/task-types", lambda c: c.task_types.list(search="x")),
    ("/v1/cases", lambda c: c.cases.list(ids=["c1"])),
    ("/v1/threads", lambda c: c.threads.list(graph="g")),
    ("/v1/runs", lambda c: c.runs.list(workflow_id="wf", status=["failed"])),
    ("/v1/workflows/definitions", lambda c: c.workflows.list(status=["live"])),
    ("/v1/workflows/wf/forms", lambda c: c.workflows.forms("wf", search="x")),
    ("/v1/workflows/wf/batches", lambda c: c.workflows.batches("wf", sort_order="asc")),
]


@pytest.mark.parametrize(("path", "call"), LISTS, ids=[p for p, _ in LISTS])
def test_every_agents_list_follows_every_page_at_the_maximum_size(path: str, call: Any) -> None:
    seen: list[httpx.Request] = []
    assert list(call(client(three_pages(seen)))) == ["row1", "row2", "row3"]
    assert [r.url.path.removeprefix("/api/agents") for r in seen] == [path] * 3
    assert {r.url.params["pageSize"] for r in seen} == {"50"}


def test_a_run_list_sends_workflow_id_camel_cased_and_never_the_old_name() -> None:
    seen: list[httpx.Request] = []
    list(client(three_pages(seen)).runs.list(workflow_id="wf"))
    assert seen[0].url.params["workflowId"] == "wf" and "workflow_id" not in seen[0].url.params


def test_a_batch_start_sends_only_the_declared_fields() -> None:
    bodies: list[Any] = []

    def handler(r: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(r.content))
        return httpx.Response(200, json={"success": True, "data": {"batchId": "b1"}})

    client(handler).workflows.start_batch("wf", "file1", mode="test", dry_run=True)
    client(handler).workflows.start_batch("wf", "file1")
    assert bodies == [{"fileId": "file1", "mode": "test", "dryRun": True}, {"fileId": "file1"}]


def test_a_batch_csv_comes_back_as_its_text() -> None:
    """The results route answers CSV, not JSON; the client hands back the text, never None."""
    body = 'file,path,status\r\n"a, b.pdf",/x,failed\r\n'

    def handler(r: httpx.Request) -> httpx.Response:
        assert r.url.path.endswith("/v1/batches/b1/results.csv")
        return httpx.Response(200, text=body, headers={"content-type": "text/csv"})

    assert client(handler).workflows.batch_csv("b1") == body


def test_waiting_groups_come_back_as_their_list() -> None:
    """The waiting route answers {data: [...]} inside the envelope; the client hands back the groups themselves."""
    groups = [{"name": "Batch002", "held": 2, "since": "2026-12-02T09:00:00Z"}]

    def handler(r: httpx.Request) -> httpx.Response:
        assert r.url.path.endswith("/v1/workflows/wf/batches/waiting")
        return httpx.Response(200, json={"success": True, "data": {"data": groups}})

    assert client(handler).workflows.waiting_groups("wf") == groups


def test_an_inbox_refused_to_a_teammate_raises_not_found() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        error = {"code": "not_found", "message": "No such thread", "status": 404}
        return httpx.Response(404, json={"success": False, "error": error})

    with pytest.raises(NotFound):
        client(handler).threads.inbox("th1")


def cursor_pages(seen: list[httpx.Request]) -> Any:
    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        n = int(r.url.params.get("cursor", "0")) + 1
        body = {"data": [f"row{n}"], "nextCursor": str(n) if n < 3 else None}
        return httpx.Response(200, json={"success": True, "data": body})

    return handler


def test_tool_options_follows_next_cursor_and_never_asks_above_the_maximum() -> None:
    seen: list[httpx.Request] = []
    assert client(cursor_pages(seen)).agents.tool_options("x") == ["row1", "row2", "row3"]
    assert [r.url.params.get("cursor") for r in seen] == [None, "1", "2"]
    assert {r.url.params["limit"] for r in seen} == {"50"}


def test_every_thread_follows_every_page_at_the_maximum_size() -> None:
    seen: list[httpx.Request] = []
    assert client(three_pages(seen)).chat.every_thread(test=True) == ["row1", "row2", "row3"]
    assert {r.url.params["pageSize"] for r in seen} == {"50"}
    assert {r.url.params["test"] for r in seen} == {"true"}
