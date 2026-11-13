"""A base's sync settings reaching the syncs of its sources, by failure mode: a base that reviews changes serving a
new version before anyone approved it; an item removed at its source taken out of a base that keeps such items, or
kept without saying so; and a new source of a base splitting by the kind's defaults instead of the base's."""

from __future__ import annotations

from typing import Any

import httpx

from . import test_tool_sources as tool_source
from .test_bases_and_sources import data
from .test_tool_sources import kb, tools  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures

OWNER = "james@harborpine.example"


async def base(client: httpx.AsyncClient, name: str, **settings: Any) -> str:
    body = {"name": name, "owner": OWNER, **settings}
    return str(data(await client.post("/v1/knowledge-bases", json=body), 201)["id"])


async def texts(client: httpx.AsyncClient, kb_id: str, question: str) -> list[str]:
    body = {"kbIds": [kb_id], "question": question}
    return [p["text"] for p in data(await client.post("/v1/knowledge-bases/search", json=body))["passages"]]


async def test_review_mode_leaves_the_old_version_searchable_until_approved(client: httpx.AsyncClient) -> None:
    kb_id = await base(client, "Rates", sync={"changes": "review"})
    src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rate desk", "kbIds": [kb_id]}), 201)
    rate = {"name": "fixed-30", "title": "Thirty-year fixed", "text": "The thirty-year fixed rate is 6.1 percent."}
    data(await client.post(f"/v1/sources/{src['id']}/items", json=rate))
    moved = data(
        await client.post(
            f"/v1/sources/{src['id']}/items", json={**rate, "text": "The thirty-year fixed rate is 5.9 percent."}
        )
    )
    assert moved["item"]["version"] == "v1", moved
    assert ["6.1" in t for t in await texts(client, kb_id, "thirty-year fixed rate")] == [True]
    waiting = data(await client.get("/v1/knowledge-changes", params={"view": "open"}))["data"]
    [held] = [c for c in waiting if c["documentId"] == moved["item"]["id"]]
    assert held["canDecide"] and held["toVersion"] == "v2", held
    data(await client.post("/v1/knowledge-changes/decide", json={"ids": [held["id"]], "decision": "approve"}))
    found = await texts(client, kb_id, "thirty-year fixed rate")
    assert found and all("5.9" in t for t in found), found


async def test_keep_and_flag_keeps_a_removed_item_searchable_and_marked(
    kb: httpx.AsyncClient,  # noqa: F811 - the tool-source fixture
    tools: tool_source.FakeTools,  # noqa: F811
) -> None:
    src = await tool_source.source(kb)
    # The strictest of the bases a source feeds wins: one keeps removed items, so they are kept.
    keeps = await base(kb, "Help kept", sourceIds=[src["id"]], sync={"removedAtSource": "keep"})
    await base(kb, "Help removed", sourceIds=[src["id"]])
    await tool_source.sync(kb, src["id"])
    del tools.articles["ka2"]
    run = await tool_source.sync(kb, src["id"], full=True)
    assert run["counts"]["deleted"] == 0, run
    lost = (await tool_source.items(kb, src["id"]))["Report a lost card"]
    assert lost["status"] == "indexed" and "removed at its source" in (lost.get("warning") or "").lower(), lost
    body = {"kbIds": [keeps], "question": "report lost card block"}
    found = data(await kb.post("/v1/knowledge-bases/search", json=body))["passages"]
    assert "Report a lost card" in {p["title"] for p in found}, found


async def test_a_new_source_splits_with_the_base_defaults(client: httpx.AsyncClient) -> None:
    kb_id = await base(client, "Rate tables", sourceDefaults={"strategies": ["fixed"], "size": 200, "overlap": 20})
    src = data(await client.post("/v1/sources", json={"type": "push", "name": "Rate sheets", "kbIds": [kb_id]}), 201)
    assert (src["ingest"]["strategies"], src["ingest"]["size"], src["ingest"]["overlap"]) == (["fixed"], 200, 20)
    alone = data(await client.post("/v1/sources", json={"type": "push", "name": "Loose notes"}), 201)
    assert alone["ingest"]["strategies"] != ["fixed"], alone["ingest"]
