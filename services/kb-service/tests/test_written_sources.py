"""Typed text and push sources, by failure mode: a pushed item stored but never searchable, the same item sent again
making a second version or a second run, new content under a known name making a second document, an item written
into a source that takes its items from elsewhere, content that is not base64 stored as garbage, and the two kinds
missing from what Add source lists."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from .test_bases_and_sources import data

BASE = {"name": "Card disputes", "owner": "james@harborpine.example"}
ITEM = {
    "name": "chargeback-window",
    "title": "Chargeback window",
    "text": "## Window\n\nA chargeback is raised within 120 days.",
}


async def written_source(client: httpx.AsyncClient, kind: str = "push") -> tuple[dict[str, Any], dict[str, Any]]:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)
    src = data(await client.post("/v1/sources", json={"type": kind, "name": "Dispute rules", "kbIds": [kb["id"]]}), 201)
    return kb, src


async def runs(client: httpx.AsyncClient, source_id: str) -> int:
    return int(data(await client.get(f"/v1/sources/{source_id}/runs"))["pagination"]["total"])


async def test_a_pushed_item_is_searchable_and_sending_it_again_changes_nothing(client: httpx.AsyncClient) -> None:
    kb, src = await written_source(client)
    first = data(await client.post(f"/v1/sources/{src['id']}/items", json=ITEM))
    assert (first["outcome"], first["item"]["status"], first["item"]["version"]) == ("created", "indexed", "v1"), first
    found = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "chargeback days"}))
    assert found["citations"] and "120 days" in found["chunks"][0]["text"], found
    made = await runs(client, src["id"])
    again = data(await client.post(f"/v1/sources/{src['id']}/items", json=ITEM))
    assert (again["outcome"], again["item"]["id"], again["item"]["version"]) == ("unchanged", first["item"]["id"], "v1")
    assert await runs(client, src["id"]) == made, "sending the same item again started a sync"


async def test_new_content_under_a_known_name_is_its_next_version(client: httpx.AsyncClient) -> None:
    kb, src = await written_source(client, "text")
    first = data(await client.post(f"/v1/sources/{src['id']}/items", json=ITEM))
    edited = {**ITEM, "text": "## Window\n\nA chargeback is raised within 90 days."}
    second = data(await client.post(f"/v1/sources/{src['id']}/items", json=edited))
    assert (second["outcome"], second["item"]["id"], second["item"]["version"]) == (
        "updated",
        first["item"]["id"],
        "v2",
    )
    docs = data(await client.get(f"/v1/knowledge-bases/{kb['id']}/documents"))["data"]
    assert [d["title"] for d in docs] == ["Chargeback window"], docs
    found = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "chargeback days"}))
    assert "90 days" in found["chunks"][0]["text"] and found["chunks"][0]["version"] == "v2", found


async def test_items_are_written_only_into_typed_text_and_push_sources(client: httpx.AsyncClient) -> None:
    _, src = await written_source(client, "file")
    refused = await client.post(f"/v1/sources/{src['id']}/items", json=ITEM)
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "source_not_written", refused.text


async def test_content_must_be_base64_with_its_type(client: httpx.AsyncClient) -> None:
    kb, src = await written_source(client)
    bad = await client.post(
        f"/v1/sources/{src['id']}/items", json={"name": "rules.md", "content": "not base64!", "mime": "text/markdown"}
    )
    assert bad.status_code == 400 and "base64" in bad.json()["error"]["message"], bad.text
    body = base64.b64encode(b"# Fees\n\nA dispute fee of 15 dollars applies to a lost dispute.\n").decode()
    put = data(await client.post(f"/v1/sources/{src['id']}/items", json={"name": "fees.md", "content": body,
                                                                         "mime": "text/markdown"}))  # fmt: skip
    assert put["item"]["status"] == "indexed", put
    found = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "dispute fee"}))
    assert "15 dollars" in found["chunks"][0]["text"], found


async def test_add_source_lists_typed_text_and_push_beside_files(client: httpx.AsyncClient) -> None:
    kinds = data(await client.get("/v1/knowledge/source-kinds"))
    built_in = [(k["type"], k["title"]) for k in kinds if k["group"] == "built_in"]
    assert built_in == [("file", "Files"), ("text", "Typed text"), ("push", "Pushed by API")], built_in
