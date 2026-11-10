"""A website source through kb-service, with the website plugin's answers faked as tools-service gives them, by
failure mode: a page robots.txt refuses (or a rule excludes) staying in search, a page read while following links
fetched again, a page that left the site kept until a weekly listing, a whole-site fetch run four at a time, and a
preview that stores something or never reaches the plugin."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import create_kb_app
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import due
from ops_kb.search import HybridRetriever
from ops_kb.service import KnowledgeService, Who
from ops_kb.store import KnowledgeStore
from ops_kb.tool_sources import Answer
from ops_service_kit.errors import Conflict
from ops_service_kit.settings import Settings
from ops_store import isolation

from .readings_fake import LocalReadings
from .test_bases_and_sources import data
from .test_rebuild import finished

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
        # The pace the listing names (a site's Crawl-delay), and when each page fetch arrived.
        self.pace: float | None = None
        self.arrived: list[float] = []
        # The hosts the account lists, as tools-service's egress check reads them; who asked about each, and whether
        # the asker sent a person's credentials.
        self.listed = {"help.northbank.test"}
        self.asked: list[tuple[str, bool]] = []

    async def source_hosts(
        self, tenant_id: str, team_id: str, cfg: dict[str, Any], *, credentials: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        starts = cast(list[str], cfg["values"].get("start") or [])
        hosts = sorted({u.split("://", 1)[-1].split("/")[0] for u in starts})
        self.asked += [(h, bool(credentials)) for h in hosts]
        return [
            {"host": h, "state": "allowed"} if h in self.listed else {"host": h, "state": "waiting", "runKey": "EGH-1"}
            for h in hosts
        ]

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        return [
            {
                "plugin": "opsai.web", "source": "site", "title": "Website", "listTool": LIST, "getTool": GET,
                "previewTool": PREVIEW, "listsWhole": True, "fetchAtOnce": 1, "getTakesTag": True,
                "needsConnection": False, "schedule": {"kind": "daily"}, "site": True,
                "inputs": {"start": {"type": "array"}, "exclude": {"type": "array", "required": False}},
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
                # A page with no sitemap date: its listing time moves with its text, as a sitemap's lastmod would.
                row: dict[str, Any] = {"id": url, "title": url, "url": url, "updated_at": f"2026-11-09T{len(body):06d}"}
                if url in self.refused:
                    row["skipped"] = self.refused[url]
                elif url in self.inline:
                    row |= {"content": body, "mime": "text/html", "encoding": "text", "marker": f'"{len(body)}"'}
                rows.append(row)
            listing: dict[str, Any] = {"items": rows}
            if self.pace is not None:
                listing["pace_s"] = self.pace
            return Answer(True, listing)
        self.arrived.append(time.monotonic())
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


FOOTER = "Northbank is a trading name of Northbank plc, registered in England."


async def test_a_sites_own_settings_are_edited_as_its_plugin_declares_them(kb: httpx.AsyncClient) -> None:
    """A site's rules saved without the plugin's check would send a crawl what it cannot read; one the plugin does not
    declare must be refused, and the source must say what it is (kind) and where it starts."""
    src, _ = await site_source(kb)
    assert (src["kind"], src["scopeSummary"]) == ("web", "help.northbank.test"), src
    saved = data(await kb.patch(f"/v1/sources/{src['id']}", json={"values": {"exclude": ["/lending/archive/**"]}}))
    assert saved["config"]["values"] == {"start": [f"{SITE}/"], "exclude": ["/lending/archive/**"]}, saved["config"]
    bad = await kb.patch(f"/v1/sources/{src['id']}", json={"values": {"crawlEverything": True}})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_source_values", bad.text


async def test_a_website_source_starts_with_a_websites_cleaning(kb: httpx.AsyncClient) -> None:
    src, _ = await site_source(kb)
    assert src["cleaning"] == {"furniture": True, "mainContent": True, "siteRepeats": True, "duplicates": "flag"}
    assert src["ingest"]["strategies"] == ["clean", "structure", "context_headers"]


async def test_a_line_on_most_pages_of_the_site_is_dropped_and_pages_rebuilt_without_a_fetch(
    kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    web.pages = {
        f"{SITE}/p{n}": html(f"Page {n}", f"Topic {n} explains loan step {n} in detail for borrowers.</p><p>{FOOTER}")
        for n in range(4)
    }
    src, base = await site_source(kb)
    first = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    assert first["counts"]["upserted"] == 4, first
    web.calls.clear()
    runs = data(await kb.get(f"/v1/sources/{src['id']}/runs"))["data"]
    rebuild = next(r for r in runs if r["trigger"] == "settings")
    done = await finished(kb, rebuild["id"])
    assert (done["status"], done["counts"]["rebuilt"]) == ("success", 4), done
    assert web.calls == [], "the rebuild reads the snapshots"
    assert await search(kb, base["id"], "trading name Northbank plc registered England") == []
    assert await search(kb, base["id"], "loan step 2 borrowers")


async def test_source_kinds_list_the_built_in_kinds_then_each_apps_knowledge_source(kb: httpx.AsyncClient) -> None:
    kinds = data(await kb.get("/v1/knowledge/source-kinds"))
    assert [(k["type"], k["title"]) for k in kinds] == [
        ("file", "Files"), ("text", "Typed text"), ("push", "Pushed by API"), ("tool", "Website"),
    ]  # fmt: skip
    web_kind = kinds[3]
    assert (web_kind["site"], web_kind["needsConnection"], web_kind["connected"], web_kind["previews"]) == (
        True, False, True, True,
    )  # fmt: skip
    # Add source's Review shows what create applies: a website's cleaning and its daily check, files' manual sync.
    assert web_kind["kind"] == "web" and web_kind["defaults"]["cleaning"]["furniture"] is True
    assert web_kind["defaults"]["schedule"] == {"kind": "daily", "time": "02:00", "tz": "UTC"}
    assert kinds[0]["defaults"]["schedule"] == {"kind": "manual"}


async def test_page_fetches_keep_to_the_slower_of_the_sources_rate_and_its_crawl_delay(
    kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    """Each fetch is its own call, so the plugin's own pacing never spaced them: a sync read every changed page at
    once, whatever the site asked for."""
    for n in range(6):
        web.pages[f"{SITE}/help/{n}"] = html(f"Help {n}", f"Help page number {n} about loans.")
    web.pace = 0.2
    src, _ = await site_source(kb)
    data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    gaps = [b - a for a, b in zip(web.arrived, web.arrived[1:], strict=False)]
    assert len(web.arrived) == 8 and min(gaps) >= 0.18, gaps


async def test_a_page_whose_text_did_not_change_keeps_its_version_whatever_its_bytes(
    kb: httpx.AsyncClient, web: WebPlugin
) -> None:
    """A page with no lastmod or ETag is fetched each run; served with a new timestamp in its footer it became a new
    version every sync, with every piece split, questioned and embedded again."""
    url = f"{SITE}/lending/fees"
    web.pages[url] = html("Fees", "An early repayment charge may apply.") + "<footer>Served 10:00</footer>"
    src, _ = await site_source(kb)
    data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    web.pages[url] = html("Fees", "An early repayment charge may apply.") + "<footer>Served 10:00:59 UTC</footer>"
    again = data(await kb.post(f"/v1/sources/{src['id']}/sync"))
    item = next(i for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"] if i["path"] == url)
    assert item["version"] == "v1" and again["counts"]["unchanged"] >= 1, (item["version"], again["counts"])


async def beat(engine: AsyncEngine, tmp_path: Any, web: WebPlugin, tenant: str, source_id: str) -> bool:
    """The schedule's pass for this one source, as run_due makes it: whether it was due and synced."""
    files = KnowledgeFiles(tmp_path)
    service = KnowledgeService(KnowledgeStore(engine), files, HybridRetriever(engine), StaticAgents(), tools=web,  # type: ignore[arg-type]
                               readings=LocalReadings(files))  # fmt: skip
    with isolation.tenant_wide("test: the schedule's pass", tenant_id=tenant):
        [s] = [s for s in await service.store.sources(tenant) if s["id"] == source_id]
    assert due(service, s, datetime.now(UTC)), "a source waiting for its host is due whatever its schedule"
    with isolation.scope(tenant, str(s["team_id"])):
        try:
            await service.scheduled_sync(Who(tenant, "knowledge schedule", str(s["team_id"])), s)
        except Conflict as e:
            assert e.code == "host_waiting", e
            return False
    return True


async def test_a_builders_new_site_is_fetched_only_once_an_admin_approves_its_host(
    kb: httpx.AsyncClient, web: WebPlugin, engine: AsyncEngine, tenant: str, tmp_path: Any
) -> None:
    """A source's site bypassed the account's new-hosts rule: a builder's new address was crawled with no admin's
    approval. Adding it asks as the builder, the source waits and says on which host, and nothing is fetched."""
    web.listed.clear()
    body = {
        "type": "tool",
        "name": "Lending help",
        "sync": True,
        "schedule": {"kind": "manual"},
        "config": {"plugin": "opsai.web", "source": "site", "values": {"start": [f"{SITE}/"]}},
    }
    # The builder's own sign-in rides with the request, as the console's does.
    src = data(await kb.post("/v1/sources", json=body, headers={"X-Dev-User": "james@harborpine.example"}), 201)
    assert src["waitingHosts"] == [{"host": "help.northbank.test", "runKey": "EGH-1"}], src
    assert web.asked == [("help.northbank.test", True)], "asked as the builder, under the account's rule"
    refused = await kb.post(f"/v1/sources/{src['id']}/sync")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "host_waiting", refused.text
    assert "Waiting for an admin to approve help.northbank.test" in refused.json()["error"]["message"]
    await asyncio.sleep(0.2)
    assert web.calls == [], "nothing is listed or fetched before the approval"
    assert not await beat(engine, tmp_path, web, tenant, src["id"]), "the schedule's pass waits too"
    # The beat reads every tenant's due sources; this one's items and runs say it took nothing in.
    assert data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"] == []
    # The admin lists the host (from the source, or on the Egress page); the next schedule pass syncs it, though
    # its own schedule is manual.
    web.listed.add("help.northbank.test")
    assert await beat(engine, tmp_path, web, tenant, src["id"])
    items = data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]
    assert len(items) == len(web.pages), items
    assert data(await kb.get(f"/v1/sources/{src['id']}"))["waitingHosts"] == []
