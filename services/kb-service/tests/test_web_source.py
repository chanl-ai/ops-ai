"""A website source through kb-service, with the website plugin's answers faked as tools-service gives them, by
failure mode: a page robots.txt refuses (or a rule excludes) staying in search, a page read while following links
fetched again, a page that left the site kept until a weekly listing, a whole-site fetch run four at a time, and a
preview that stores something or never reaches the plugin."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.tool_sources import Answer
from ops_service_kit.settings import Settings

from .readings_fake import LocalReadings
from .test_bases_and_sources import data

LIST, GET, PREVIEW = "web_list_pages", "web_get_page", "web_preview_site"
SITE = "https://help.northbank.test"


def html(title: str, body: str) -> str:
    return f"<html><head><title>{title}</title></head><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"


class WebPlugin:
    def __init__(self) -> None:
        self.pages = {
            f"{SITE}/lending/early-repayment": html("Early repayment", "Repay all or part of your loan at any time."),
            f"{SITE}/lending/fees": html("Fees", "An early repayment charge of up to 58 days interest may apply."),
        }
        self.refused: dict[str, str] = {}
        self.inline: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.at_once = 0
        self.most = 0

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        return [
            {
                "plugin": "opsai.web", "source": "site", "title": "Website", "listTool": LIST, "getTool": GET,
                "previewTool": PREVIEW, "listsWhole": True, "fetchAtOnce": 1, "getTakesTag": True,
                "needsConnection": False, "inputs": {"start": {"type": "array"}}, "schedule": {"kind": "daily"},
            }
        ]  # fmt: skip

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        self.calls.append((tool, dict(args)))
        if tool == PREVIEW:
            return Answer(True, {"found": 2, "will_fetch": 1, "capped": False, "pages": [
                {"id": f"{SITE}/a", "outcome": "Will fetch", "will_fetch": True},
                {"id": f"{SITE}/admin/", "outcome": "Refused by robots.txt", "will_fetch": False}]})  # fmt: skip
        if tool == LIST:
            rows: list[dict[str, Any]] = []
            for url, body in self.pages.items():
                row: dict[str, Any] = {"id": url, "title": url, "updated_at": "2026-11-09T00:00:00Z", "url": url}
                if url in self.refused:
                    row["skipped"] = self.refused[url]
                elif url in self.inline:
                    row |= {"content": body, "mime": "text/html", "encoding": "text", "marker": f'"{len(body)}"'}
                rows.append(row)
            return Answer(True, {"items": rows})
        self.at_once += 1
        self.most = max(self.most, self.at_once)
        try:
            body = self.pages[str(args["id"])]
            if args.get("tag") == f'"{len(body)}"':
                return Answer(True, {"unchanged": True})
            return Answer(True, {"id": args["id"], "title": args["id"], "mime": "text/html", "encoding": "text",
                                 "content": body, "url": args["id"], "marker": f'"{len(body)}"'})  # fmt: skip
        finally:
            self.at_once -= 1

    def got(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == GET]


@pytest.fixture
def web() -> WebPlugin:
    return WebPlugin()


@pytest.fixture
async def kb(engine: AsyncEngine, tenant: str, web: WebPlugin, tmp_path: Any) -> AsyncIterator[httpx.AsyncClient]:
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email="james@harborpine.example", tenant_id=tenant)
    files = KnowledgeFiles(tmp_path)
    app = create_kb_app(engine, auth=auth, files=files, agents=StaticAgents(), tools=web,  # type: ignore[arg-type]
                        readings=LocalReadings(files), schedule=False)  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


async def site_source(kb: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "type": "tool",
        "name": "Lending help",
        "config": {"plugin": "opsai.web", "source": "site", "values": {"start": [f"{SITE}/"]}},
    }
    src = data(await kb.post("/v1/sources", json=body), 201)
    base = data(
        await kb.post(
            "/v1/knowledge-bases",
            json={"name": "Lending", "owner": "james@harborpine.example", "sourceIds": [src["id"]]},
        ),
        201,
    )
    return src, base


async def search(kb: httpx.AsyncClient, kb_id: str, question: str) -> list[dict[str, Any]]:
    return data(await kb.post("/v1/knowledge-bases/search", json={"kbIds": [kb_id], "question": question}))["passages"]


async def test_a_page_now_refused_or_gone_leaves_search_on_the_next_run(kb: httpx.AsyncClient, web: WebPlugin) -> None:
    src, base = await site_source(kb)
    first = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert first["counts"]["upserted"] == 2, first
    assert await search(kb, base["id"], "early repayment charge 58 days interest")
    web.refused[f"{SITE}/lending/fees"] = "Refused by robots.txt"
    run = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert run["counts"]["deleted"] == 1 and any("Refused by robots.txt" in line for line in run["log"]), run
    assert await search(kb, base["id"], "early repayment charge 58 days interest") == []
    del web.pages[f"{SITE}/lending/early-repayment"]
    assert data(await kb.post(f"/v1/sources/{src['id']}/sync"))["counts"]["deleted"] == 1


async def test_a_page_read_while_listing_is_not_fetched_again_and_fetches_go_one_at_a_time(
    kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    src, _ = await site_source(kb)
    web.inline.add(f"{SITE}/lending/fees")
    run = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert run["counts"]["upserted"] == 2 and web.got() == [f"{SITE}/lending/early-repayment"], (run, web.calls)
    assert web.most == 1
    web.calls.clear()
    again = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert again["counts"]["upserted"] == 0, again


async def test_the_preview_asks_the_plugin_and_stores_nothing(kb: httpx.AsyncClient, web: WebPlugin) -> None:
    body = {"config": {"plugin": "opsai.web", "source": "site", "values": {"start": [f"{SITE}/"]}}}
    out = data(await kb.post("/v1/sources/preview", json=body))
    assert (out["found"], out["willFetch"], out["pages"][1]["outcome"]) == (2, 1, "Refused by robots.txt"), out
    assert data(await kb.get("/v1/sources"))["data"] == []
    bad = await kb.post("/v1/sources/preview", json={"config": {"plugin": "opsai.web", "source": "site", "values": {}}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_source_values", bad.text
