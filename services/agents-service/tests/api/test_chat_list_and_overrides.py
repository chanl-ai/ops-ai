"""Chat thread list and the fields M1b reads, by failure mode: overrides or attachments dropped or rewritten on their
way into the run input; a search that misses a thread's messages; a cursor page that repeats or skips a thread; a
cursor replayed under another sort answering 500; a chat read, listed or changed by anyone but its owner."""

from __future__ import annotations

import base64
import json
from typing import Any

from httpx import AsyncClient
from sqlalchemy.dialects import mssql, mysql, postgresql, sqlite

from ops_agents.api.deps import Runtime
from ops_agents.api.runs import graph_store
from ops_agents.store.chat_search import matching_query
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
from tests.api.test_write_approval_policy import (
    dev_platform,  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
    person,
)

QUESTION = "What is the daily wire limit for a personal account?"


async def test_overrides_and_attachments_reach_the_run_input_unchanged(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    thread_overrides = {"toolsOff": ["place_wire_hold"]}
    turn_overrides = {"knowledgeBaseIds": ["kb_people"]}
    uploaded = await client.post(
        "/chat/attachments",
        params={"name": "limits.txt"},
        content=b"Daily wire limit: 25,000.",
        headers={"Content-Type": "text/plain"},
    )
    assert uploaded.status_code == 201, uploaded.text
    file = uploaded.json()["data"]
    res = await client.post(
        "/chat/threads",
        json={"agentId": "ag_fraud", "kbIds": ["kb_people"], "overrides": thread_overrides, "attachments": [file]},
    )
    assert res.status_code == 201, res.text
    tid = res.json()["data"]["id"]
    await send(client, tid, {"content": QUESTION, "overrides": turn_overrides, "attachments": [file]})
    run = (await graph_store(rt).runs(tid))[0]
    given: dict[str, Any] = run["input"]["input"]
    assert given["thread_overrides"] == thread_overrides
    assert given["overrides"] == turn_overrides
    assert given["thread_attachments"] == [file] and given["attachments"] == [file]
    assert given["settings"]["toolsOff"] == ["place_wire_hold"] and given["settings"]["knowledgeBaseIds"] == [
        "kb_people"
    ]


async def test_a_message_without_overrides_adds_none(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": QUESTION})
    given = (await graph_store(rt).runs(thread["id"]))[0]["input"]["input"]
    assert not {"overrides", "thread_overrides", "thread_attachments"} & set(given)
    assert given["settings"]["sources"] == {"model": "agent", "knowledgeBaseIds": "started"}


async def test_search_finds_a_question_past_the_title(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    long_question = "What is the daily wire limit for a personal account opened by a minor in Saskatchewan?"
    hit, miss = await new_thread(client), await new_thread(client)
    await send(client, hit["id"], {"content": long_question})
    await send(client, miss["id"], {"content": QUESTION})
    row = (await client.get(f"/chat/threads/{hit['id']}")).json()["data"]
    assert "Saskatchewan" not in row["title"]  # the title stops at 48 characters, so only the question can match
    found = (await client.get("/chat/threads", params={"search": "saskatchewan"})).json()["data"]
    assert [t["id"] for t in found["data"]] == [hit["id"]]
    assert found["pagination"]["total"] == 1


async def test_cursor_pages_neither_repeat_nor_skip_a_thread(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(5)]
    seen: list[str] = []
    page = (await client.get("/chat/threads", params={"pageSize": 2})).json()["data"]
    seen += [t["id"] for t in page["data"]]
    cursor = page.get("nextCursor")
    await new_thread(client)  # a thread started between pages lands before the cursor, so no row shifts
    while cursor:
        page = (await client.get("/chat/threads", params={"pageSize": 2, "cursor": cursor})).json()["data"]
        seen += [t["id"] for t in page["data"]]
        cursor = page.get("nextCursor")
    assert sorted(seen) == sorted(made) and len(seen) == len(set(seen))
    bad = await client.get("/chat/threads", params={"cursor": "not-a-cursor"})
    assert bad.status_code == 400


async def test_a_cursor_from_another_sort_or_with_a_foreign_key_is_refused_not_a_500(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    for _ in range(3):
        await new_thread(client)
    by_title = (await client.get("/chat/threads", params={"pageSize": 1, "sortBy": "title"})).json()["data"]
    cursor = by_title["nextCursor"]
    same = await client.get("/chat/threads", params={"pageSize": 1, "sortBy": "title", "cursor": cursor})
    assert same.status_code == 200
    other = await client.get("/chat/threads", params={"pageSize": 1, "sortBy": "messageCount", "cursor": cursor})
    assert other.status_code == 400, other.text
    flipped = await client.get(
        "/chat/threads", params={"pageSize": 1, "sortBy": "title", "sortOrder": "desc", "cursor": cursor}
    )
    assert flipped.status_code == 400
    foreign = base64.urlsafe_b64encode(json.dumps(["lastMessageAt:desc", {"a": 1}, "th_x"]).encode()).decode()
    assert (await client.get("/chat/threads", params={"cursor": foreign})).status_code == 400


async def test_only_the_owner_reads_lists_or_changes_a_chat(dev_platform: AsyncClient) -> None:  # noqa: F811
    james, teammate, outsider = (
        person("usr_james", ["team_ops"]),
        person("usr_maya", ["team_ops"]),
        person("usr_nadia", ["team_fraud"]),
    )
    made = await dev_platform.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=james)
    assert made.status_code == 201, made.text
    tid = made.json()["data"]["id"]
    assert (await dev_platform.get(f"/chat/threads/{tid}", headers=james)).status_code == 200
    for other in (teammate, outsider):
        assert (await dev_platform.get(f"/chat/threads/{tid}", headers=other)).status_code == 404
        assert (await dev_platform.delete(f"/chat/threads/{tid}", headers=other)).status_code == 404
        listed = (await dev_platform.get("/chat/threads", headers=other)).json()["data"]["data"]
        assert tid not in [t["id"] for t in listed]
    assert tid in [t["id"] for t in (await dev_platform.get("/chat/threads", headers=james)).json()["data"]["data"]]


async def test_a_renamed_chat_is_found_by_its_new_title(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, _ = stack
    tid = (await new_thread(client))["id"]
    renamed = await client.patch(f"/chat/threads/{tid}", json={"title": "Quarterly sanctions review"})
    assert renamed.status_code == 200, renamed.text
    found = (await client.get("/chat/threads", params={"search": "sanctions"})).json()["data"]["data"]
    assert [t["id"] for t in found] == [tid]


def test_search_reads_plain_columns_on_every_dialect() -> None:
    """Portability rule D5: no JSON operator in the search, so MySQL and Azure SQL run the same statement."""
    for dialect in (postgresql.dialect(), mysql.dialect(), mssql.dialect(), sqlite.dialect()):
        with tenant_scope("acme"):
            sql = str(matching_query("wire").compile(dialect=dialect)).lower()
        assert "json" not in sql and "->" not in sql and "#>>" not in sql, (dialect.name, sql)
        assert "chat_search.questions" in sql
