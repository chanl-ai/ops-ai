"""One record per model call, by failure mode: the fold losing a field the budget, replay or journal needs, and a
regenerate answered from an earlier record instead of calling the model again."""

from __future__ import annotations

from typing import Any, cast

from httpx import AsyncClient

from ops_agents.api.deps import Runtime
from ops_agents.store.model_calls import ModelCallLedger
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture

QUESTION = "What is the daily wire limit for a personal account?"


async def records(rt: Runtime, thread_id: str) -> list[dict[str, Any]]:
    assert rt.graph_store is not None
    return await ModelCallLedger(rt.graph_store.engine).calls(thread_id)


async def test_a_kernel_model_call_is_one_record_with_every_field(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    thread = await new_thread(client)
    await send(client, thread["id"], {"content": QUESTION})
    rows = [r for r in await records(rt, thread["id"]) if r["kind"] == "model"]
    assert len(rows) == 1
    r = rows[0]
    assert r["model_alias"] and r["run_id"] and r["step"] == "agent" and r["task"]
    assert r["input_tokens"] > 0 and r["output_tokens"] > 0 and r["calls"] == 1
    assert r["latency_ms"] is not None and len(r["request_hash"]) == 64 and r["response"]
    cost = (await client.get(f"/v1/threads/{thread['id']}/state")).json()["data"]["cost"]
    assert (cost["calls"], cost["inputTokens"], cost["outputTokens"]) == (1, r["input_tokens"], r["output_tokens"])
    state = cast(dict[str, Any], (await client.get(f"/chat/threads/{thread['id']}")).json()["data"])
    assert state["messages"][-1]["model"].startswith("function:scripted")


async def test_a_regenerate_calls_the_model_again(stack: tuple[AsyncClient, Runtime]) -> None:  # noqa: F811
    client, rt = stack
    thread = await new_thread(client)
    _, events = await send(client, thread["id"], {"content": QUESTION})
    await send(client, thread["id"], {"content": "", "regenerate": events[0]["messageId"]})
    rows = [r for r in await records(rt, thread["id"]) if r["kind"] == "model"]
    # A new step with its own task: a fresh call and its own record, never the earlier response replayed.
    assert len(rows) == 2 and rows[0]["task"] != rows[1]["task"] and rows[0]["run_id"] != rows[1]["run_id"]
