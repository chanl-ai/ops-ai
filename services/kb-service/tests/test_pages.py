"""A page written in the console, by failure mode: a page that is stored but never indexed, a page that
cannot be found by a question, a second save under the same title made a second document, and an empty page saved."""

from __future__ import annotations

import httpx

from .test_bases_and_sources import data

BASE = {"name": "Teller procedures", "owner": "james@harborpine.example"}


async def test_a_page_is_indexed_found_and_saved_again_as_its_next_version(client: httpx.AsyncClient) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)
    body = {"title": "Cash drawer limits", "text": "## Drawer limit\n\nA teller drawer holds at most 5,000 dollars."}
    page = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json=body), 201)
    assert (page["title"], page["status"], page["version"]) == ("Cash drawer limits", "indexed", "v1"), page
    answer = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/query", json={"question": "teller drawer limit"}))
    assert answer["citations"] and answer["citations"][0]["section"].endswith("Drawer limit"), answer
    edited = {**body, "text": "## Drawer limit\n\nA teller drawer holds at most 4,000 dollars."}
    again = data(await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json=edited), 201)
    assert again["id"] == page["id"] and again["version"] == "v2", again
    docs = data(await client.get(f"/v1/knowledge-bases/{kb['id']}/documents"))["data"]
    assert [d["title"] for d in docs] == ["Cash drawer limits"]


async def test_an_empty_page_is_refused(client: httpx.AsyncClient) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)
    empty = await client.post(f"/v1/knowledge-bases/{kb['id']}/pages", json={"title": "Blank", "text": "  "})
    assert empty.status_code == 400 and "text" in empty.json()["error"]["message"], empty.text


async def test_a_base_whose_pages_source_holds_files_takes_its_next_page(client: httpx.AsyncClient) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)
    body = {"type": "file", "name": f"{BASE['name']} pages", "collection": "Pages", "kbIds": [kb["id"]]}
    data(await client.post("/v1/sources", json=body), 201)
    page = await client.post(
        f"/v1/knowledge-bases/{kb['id']}/pages", json={"title": "Vault", "text": "## Vault\n\nOpen at 8."}
    )
    assert page.status_code == 201 and page.json()["data"]["status"] == "indexed", page.text
    sources = data(await client.get("/v1/sources"))["data"]
    assert [s["type"] for s in sources if s["name"] == body["name"]] == ["text"], sources
