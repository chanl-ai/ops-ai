"""Chat thread list and the fields M1b reads, by failure mode: overrides or attachments dropped or rewritten on their
way into the run input; a search that misses a thread's messages; a cursor page that repeats or skips a thread; a
cursor replayed under another sort answering 500; a chat read, listed or changed by anyone but its owner."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import replace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import mssql, mysql, postgresql, sqlite

from ops_agents.api.deps import Runtime
from ops_agents.api.runs import graph_store
from ops_agents.store.chat_list import ChatListQuery, facet_queries, page_queries
from ops_agents.store.chat_search import matching_query
from ops_agents.store.graphs import GraphStore
from ops_agents.store.tenancy import tenant_scope
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_attachments import Rig
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
    rig = Rig(rt)
    file = await rig.put(await rig.team((await new_thread(client))["id"]), "limits.txt", ["Daily wire limit: 25,000."])
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


async def test_a_pinned_chat_leads_the_list_however_many_newer_chats_there_are(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(36)]
    oldest = made[0]
    assert (await client.patch(f"/chat/threads/{oldest}", json={"pinned": True})).status_code == 200
    first = (await client.get("/chat/threads", params={"pageSize": 30})).json()["data"]
    seen = [t["id"] for t in first["data"]]
    assert seen[0] == oldest
    assert seen[1:] == made[:0:-1][:29]  # then the rest, newest first
    cursor = first.get("nextCursor")
    while cursor:
        page = (await client.get("/chat/threads", params={"pageSize": 30, "cursor": cursor})).json()["data"]
        seen += [t["id"] for t in page["data"]]
        cursor = page.get("nextCursor")
    assert sorted(seen) == sorted(made) and len(seen) == len(set(seen))


async def test_a_page_read_does_not_load_every_thread(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(12)]

    async def every_thread(*_a: Any, **_k: Any) -> list[dict[str, Any]]:
        raise AssertionError("the list read every thread to serve one page")

    monkeypatch.setattr(GraphStore, "threads", every_thread)
    page = (await client.get("/chat/threads", params={"pageSize": 5})).json()["data"]
    assert [t["id"] for t in page["data"]] == made[:6:-1]
    assert page["pagination"]["total"] == 12 and page["nextCursor"]


async def test_chats_pinned_or_answered_while_paging_are_neither_skipped_nor_repeated(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(36)]
    first = (await client.get("/chat/threads", params={"pageSize": 10})).json()["data"]
    seen = [t["id"] for t in first["data"]]
    cursor = first["nextCursor"]
    # Two chats already on the screen change: one is pinned, one is answered. Both move to the top.
    assert (await client.patch(f"/chat/threads/{seen[3]}", json={"pinned": True})).status_code == 200
    await send(client, seen[6], {"content": QUESTION})
    created = (await new_thread(client))["id"]
    while cursor:
        page = (await client.get("/chat/threads", params={"pageSize": 10, "cursor": cursor})).json()["data"]
        seen += [t["id"] for t in page["data"]]
        cursor = page.get("nextCursor")
    assert len(seen) == len(set(seen))
    assert set(seen) == set(made) and created not in seen


async def test_the_sidebar_slice_keeps_recent_chats_beside_more_than_thirty_pinned(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(36)]
    for tid in made[:31]:
        assert (await client.patch(f"/chat/threads/{tid}", json={"pinned": True})).status_code == 200
    res = await client.get("/chat/threads", params={"pageSize": 30, "recent": 5, "state": ["active", "pinned"]})
    rows = res.json()["data"]["data"]
    assert [t["pinned"] for t in rows] == [True] * 30 + [False] * 5
    assert [t["id"] for t in rows[30:]] == made[:30:-1]  # the five newest unpinned chats


async def test_sorting_by_last_message_is_the_plain_sort_with_no_pinned_first(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, _ = stack
    made = [(await new_thread(client))["id"] for _ in range(3)]
    assert (await client.patch(f"/chat/threads/{made[0]}", json={"pinned": True})).status_code == 200
    explicit = (await client.get("/chat/threads", params={"sortBy": "lastMessageAt"})).json()["data"]
    assert [t["id"] for t in explicit["data"]] == made[::-1]
    default = (await client.get("/chat/threads")).json()["data"]
    assert default["data"][0]["id"] == made[0]
    # The two orders differ, so a cursor from one is refused in the other.
    cursor = (await client.get("/chat/threads", params={"pageSize": 1})).json()["data"]["nextCursor"]
    replay = await client.get("/chat/threads", params={"pageSize": 1, "sortBy": "lastMessageAt", "cursor": cursor})
    assert replay.status_code == 400


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
    # A teammate following a link is told whose it is and reads nothing of it; outside the team it is not found.
    sealed = await dev_platform.get(f"/chat/threads/{tid}", headers=teammate)
    assert sealed.status_code == 200 and sealed.json()["data"] == {"id": tid, "readable": False}, sealed.text
    assert (await dev_platform.get(f"/chat/threads/{tid}", headers=outsider)).status_code == 404
    for other in (teammate, outsider):
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


def test_every_chat_list_statement_is_valid_transact_sql() -> None:
    """Azure SQL refuses a condition compared with 0 or 1, and a GROUP BY on an expression holding bound parameters
    (error 8120). Compiled whole, for each list shape, as the server would receive them."""
    q = ChatListQuery(
        graph="chat",
        owner_email="a@b.c",
        owner_name="A",
        states=["pinned"],
        agents=["x"],
        kbs=["k1", "k2"],
        search="wire",
    )
    with tenant_scope("acme"):
        statements: list[Any] = []
        for variant in (q, replace(q, pinned=True), replace(q, pinned=False), replace(q, test=True)):
            statements += [s for s in page_queries(variant, limit=10, after=([1, "t"], "id")) if s is not None]
            statements += list(facet_queries(variant).values())
        sqls = [str(s.compile(dialect=mssql.dialect())) for s in statements]
    for sql in sqls:
        assert ") = 0" not in sql and ") = 1" not in sql, sql
    for sql in sqls:
        for part in sql.split("GROUP BY")[1:]:
            assert re.fullmatch(r"\s*anon_\d+\.\w+\s*", part), part
