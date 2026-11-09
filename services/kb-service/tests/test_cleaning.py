"""A source's cleaning, by failure mode: page furniture indexed and cited, a cleaning change that reads the page
again, and two copies of the same text in one knowledge base both answering."""

from __future__ import annotations

from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity.fastapi import DEV_TEAM
from ops_kb.files import KnowledgeFiles

from .conftest import intakes, kb_client
from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_rebuild import finished

PAGE = b"""<html><head><title>Telling us late</title></head><body>
<nav class="site-nav"><a href="/">Home</a> <a href="/claims">Claims</a> <a href="/contact">Contact</a></nav>
<div class="cookie-banner"><p>We use cookies to remember your claim preferences.</p></div>
<main><h1>Telling us late</h1><p>You can still claim after the 30 day window if the delay did not harm our
assessment of the damage.</p></main>
<footer><p>Harbour Insurance claims line, open every day.</p></footer></body></html>"""


async def html_file(client: httpx.AsyncClient, source_id: str, name: str, body: bytes) -> None:
    stored = await intakes[client].put("t", DEV_TEAM, body, name=name, mime="text/html", actor="james")
    data(await client.post(f"/v1/sources/{source_id}/files", json={"fileIds": [stored.file_id]}))


async def source_in(client: httpx.AsyncClient, kb_ids: list[str], name: str, **settings: Any) -> dict[str, Any]:
    body = {"type": "file", "name": name, "collection": "Claims", "owner": "james@harborpine.example", "kbIds": kb_ids}
    return data(await client.post("/v1/sources", json={**body, **settings}), 201)


async def texts(client: httpx.AsyncClient, source_id: str) -> str:
    [item] = data(await client.get(f"/v1/sources/{source_id}/items"))["data"]
    return " ".join(c["text"] for c in data(await client.get(f"/v1/items/{item['id']}"))["detail"]["chunks"])


async def test_furniture_is_left_out_and_turning_it_back_on_reads_nothing_again(
    engine: AsyncEngine, tenant: str
) -> None:
    intake = KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    readings = LocalReadings(intake)
    async with kb_client(engine, tenant, files=intake, readings=readings) as client:
        src = await source_in(client, [], "Claims pages", cleaning={"furniture": True, "mainContent": True})
        await html_file(client, src["id"], "late.html", PAGE)
        data(await client.post(f"/v1/sources/{src['id']}/sync"))
        cleaned = await texts(client, src["id"])
        assert "30 day window" in cleaned
        assert "cookies" not in cleaned and "Contact" not in cleaned and "claims line" not in cleaned, cleaned
        [item] = data(await client.get(f"/v1/sources/{src['id']}/items"))["data"]
        detail = data(await client.get(f"/v1/items/{item['id']}"))
        [page] = detail["reading"]["pages"]
        assert page["readBy"] == "text" and page["removedChars"] > 40, page
        assert detail["reading"]["readerVersion"] == "reading-3" and detail["settingsUsed"]["current"] is True
        reads = len(readings.reads)
        saved = data(
            await client.patch(
                f"/v1/sources/{src['id']}", json={"cleaning": {"furniture": False, "mainContent": False}}
            )
        )
        await finished(client, saved["rebuild"]["id"])
        assert "cookies" in await texts(client, src["id"])
        assert len(readings.reads) == reads, "a cleaning change splits the stored reading again"


async def test_the_same_text_in_two_sources_of_a_base_answers_once(client: httpx.AsyncClient) -> None:
    kb = data(
        await client.post("/v1/knowledge-bases", json={"name": "Claims", "owner": "james@harborpine.example"}), 201
    )
    old = await source_in(client, [kb["id"]], "Help centre")
    new = await source_in(client, [kb["id"]], "Policy pages")
    await html_file(client, old["id"], "late.html", PAGE)
    data(await client.post(f"/v1/sources/{old['id']}/sync"))
    await html_file(client, new["id"], "late-notice.html", PAGE)
    data(await client.post(f"/v1/sources/{new['id']}/sync"))
    found = data(
        await client.post(
            "/v1/knowledge-bases/search", json={"kbIds": [kb["id"]], "question": "claim after the 30 day window delay"}
        )
    )
    assert {p["itemId"] for p in found["passages"]} == {
        data(await client.get(f"/v1/sources/{new['id']}/items"))["data"][0]["id"]
    }, found
    [older] = data(await client.get(f"/v1/sources/{old['id']}/items"))["data"]
    assert older["duplicateOf"] and "same text" in older["warning"], older
    assert data(await client.get(f"/v1/sources/{old['id']}"))["governance"]["duplicates"] == 1


async def test_skip_keeps_a_second_copy_out_of_search(client: httpx.AsyncClient) -> None:
    kb = data(
        await client.post("/v1/knowledge-bases", json={"name": "Claims", "owner": "james@harborpine.example"}), 201
    )
    old = await source_in(client, [kb["id"]], "Help centre")
    new = await source_in(client, [kb["id"]], "Policy pages", cleaning={"duplicates": "skip"})
    await html_file(client, old["id"], "late.html", PAGE)
    data(await client.post(f"/v1/sources/{old['id']}/sync"))
    await html_file(client, new["id"], "late-notice.html", PAGE)
    data(await client.post(f"/v1/sources/{new['id']}/sync"))
    [skipped] = data(await client.get(f"/v1/sources/{new['id']}/items"))["data"]
    assert skipped["status"] == "skipped" and "already in Telling us late" in skipped["warning"], skipped
    [kept] = data(await client.get(f"/v1/sources/{old['id']}/items"))["data"]
    assert kept["status"] == "indexed" and "duplicateOf" not in kept
