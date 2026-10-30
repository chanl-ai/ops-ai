"""Knowledge read through a connection's tools (c-564), by failure mode: every article fetched on every sync; a changed
one missed or a removed one kept; an attachment that outlives its article; a rate limit that restarts the sync from the
first page or loses the pages read; a refused sign-in retried every schedule; a source made on a connection that signs
in each person, which a sync with nobody behind it cannot use; and two syncs of one source at once."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth
from ops_kb.agents import StaticAgents
from ops_kb.app import _tools_service, create_kb_app  # pyright: ignore[reportPrivateUsage]
from ops_kb.files import KnowledgeFiles
from ops_kb.schedule import due
from ops_kb.tool_sources import Answer
from ops_service_kit.settings import Settings

from .test_bases_and_sources import data

LIST, GET = "salesforce_list_articles", "salesforce_get_article"


class FakeTools:
    """tools-service as kb-service sees it: the team's declared sources and the two tools, answering from `articles`."""

    def __init__(self) -> None:
        self.articles: dict[str, dict[str, Any]] = {
            "ka1": {
                "title": "Reset a card PIN",
                "updated_at": "2026-10-01T09:00:00Z",
                "body": "<p>Reset in the app.</p>",
                "children": ["ka1a"],
            },
            "ka2": {"title": "Report a lost card", "updated_at": "2026-10-02T09:00:00Z", "body": "<p>Block it.</p>"},
            "ka3": {"title": "Travel notices", "updated_at": "2026-10-03T09:00:00Z", "body": "<p>None needed.</p>"},
        }
        self.attachments = {"ka1a": {"title": "pin-steps.txt", "updated_at": "2026-10-01T09:00:00Z", "body": "Step 1."}}
        self.sign_in = "team"
        self.status = "healthy"
        self.fail: dict[str, str] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # "same": every page names itself as the next; "endless": every page names a new one.
        self.pages = ""

    async def declared(self, tenant_id: str, team_id: str) -> list[dict[str, Any]]:
        return [
            {
                "plugin": "opsai.salesforce",
                "source": "articles",
                "title": "Salesforce Knowledge articles",
                "listTool": LIST,
                "getTool": GET,
                "deletedTool": None,
                "schedule": {"kind": "daily", "time": "02:00"},
                "connectionId": "con_sf",
                "signIn": self.sign_in,
                "connectionStatus": self.status,
            }
        ]

    async def call(self, tenant_id: str, team_id: str, tool: str, args: dict[str, Any], *, act: str) -> Answer:
        self.calls.append((tool, dict(args)))
        if (code := self.fail.pop(f"{tool}:{args.get('cursor') or args.get('id') or 'first'}", None)) is not None:
            return Answer(False, code=code, message=code)
        if tool == LIST and self.pages:
            given = str(args.get("cursor") or "p0")
            nxt = given if self.pages == "same" else f"p{int(given[1:]) + 1}"
            return Answer(True, {"items": [], "next_cursor": nxt})
        if tool == LIST:
            rows = sorted(self.articles.items(), key=lambda kv: kv[1]["updated_at"])
            if args.get("since"):
                rows = [kv for kv in rows if kv[1]["updated_at"] > args["since"]]
            start = int(args.get("cursor") or 0)
            page = rows[start : start + 2]
            out: dict[str, Any] = {
                "items": [{"id": k, "title": v["title"], "updated_at": v["updated_at"]} for k, v in page]
            }
            if start + 2 < len(rows):
                out["next_cursor"] = str(start + 2)
            elif page:
                out["watermark"] = page[-1][1]["updated_at"]
            return Answer(True, out)
        item_id = str(args["id"])
        a = self.articles.get(item_id) or self.attachments[item_id]
        kids = [
            {"id": c, "title": self.attachments[c]["title"], "updated_at": self.attachments[c]["updated_at"]}
            for c in a.get("children", [])
        ]
        mime = "text/plain" if item_id in self.attachments else "text/html"
        return Answer(
            True,
            {
                "id": item_id,
                "title": a["title"],
                "updated_at": a["updated_at"],
                "mime": mime,
                "encoding": "text",
                "content": a["body"],
                "url": f"https://acme/{item_id}",
                "children": kids,
            },
        )

    def got(self) -> list[str]:
        return [str(a["id"]) for t, a in self.calls if t == GET]


@pytest.fixture
def tools() -> FakeTools:
    return FakeTools()


@pytest.fixture
async def kb(engine: AsyncEngine, tenant: str, tools: FakeTools) -> AsyncIterator[httpx.AsyncClient]:
    email = "james@harborpine.example"
    auth = Auth.for_dev(Settings(), audience="kb", name="james", email=email, tenant_id=tenant)
    app = create_kb_app(
        engine,
        auth=auth,
        files=KnowledgeFiles(Path(mkdtemp(prefix="kb-files-"))),
        agents=StaticAgents(),
        tools=tools,  # type: ignore[arg-type]
        schedule=False,
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb") as c:
        yield c


async def source(kb: httpx.AsyncClient) -> dict[str, Any]:
    body = {
        "type": "tool",
        "name": "Salesforce articles",
        "config": {"plugin": "opsai.salesforce", "source": "articles"},
    }
    return data(await kb.post("/v1/sources", json=body), 201)


async def items(kb: httpx.AsyncClient, source_id: str) -> dict[str, dict[str, Any]]:
    rows = data(await kb.get(f"/v1/sources/{source_id}/items", params={"pageSize": 50}))["data"]
    return {r["name"] if "name" in r else r["title"]: r for r in rows}


async def sync(kb: httpx.AsyncClient, source_id: str, *, full: bool = False) -> dict[str, Any]:
    return data(await kb.post(f"/v1/sources/{source_id}/sync", json={"full": full}))


async def test_a_second_sync_fetches_nothing_unchanged(kb: httpx.AsyncClient, tools: FakeTools) -> None:
    src = await source(kb)
    first = await sync(kb, src["id"])
    assert first["status"] == "success" and first["counts"]["upserted"] == 4, first  # three articles and one attachment
    assert sorted(tools.got()) == ["ka1", "ka1a", "ka2", "ka3"]
    tools.calls.clear()
    second = await sync(kb, src["id"])
    assert second["status"] == "success" and tools.got() == [], second
    assert ("salesforce_list_articles", {"since": "2026-10-03T09:00:00Z"}) in tools.calls
    # A full listing names every article again; only the ones whose marker moved are fetched, here none.
    tools.calls.clear()
    third = await sync(kb, src["id"], full=True)
    assert third["status"] == "success" and third["counts"]["unchanged"] == 3 and tools.got() == [], third


async def test_a_changed_article_is_its_next_version(kb: httpx.AsyncClient, tools: FakeTools) -> None:
    src = await source(kb)
    await sync(kb, src["id"])
    tools.articles["ka2"] |= {"updated_at": "2026-10-09T09:00:00Z", "body": "<p>Block it in the app at once.</p>"}
    tools.calls.clear()
    run = await sync(kb, src["id"])
    assert tools.got() == ["ka2"] and run["counts"]["upserted"] == 1, run
    found = {i["title"]: i for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert found["Report a lost card"]["version"] == "v2"


async def test_a_changed_article_does_not_fetch_its_unchanged_attachment_again(
    kb: httpx.AsyncClient, tools: FakeTools
) -> None:
    src = await source(kb)
    await sync(kb, src["id"])
    tools.articles["ka1"] |= {"updated_at": "2026-10-09T09:00:00Z", "body": "<p>Reset in the app, then confirm.</p>"}
    tools.calls.clear()
    await sync(kb, src["id"])
    assert tools.got() == ["ka1"], tools.got()


async def test_an_article_gone_from_the_listing_goes_with_its_attachment(
    kb: httpx.AsyncClient, tools: FakeTools
) -> None:
    src = await source(kb)
    await sync(kb, src["id"])
    del tools.articles["ka1"]
    run = await sync(kb, src["id"], full=True)
    assert run["counts"]["deleted"] == 2, run
    titles = {i["title"] for i in data(await kb.get(f"/v1/sources/{src['id']}/items"))["data"]}
    assert "Reset a card PIN" not in titles and "pin-steps.txt" not in titles and "Travel notices" in titles


async def test_a_rate_limit_mid_listing_resumes_from_the_saved_page(kb: httpx.AsyncClient, tools: FakeTools) -> None:
    src = await source(kb)
    tools.fail[f"{LIST}:2"] = "RATE_LIMITED"
    stopped = await sync(kb, src["id"])
    assert stopped["status"] == "partial", stopped
    tools.calls.clear()
    resumed = await sync(kb, src["id"])
    assert resumed["status"] == "success", resumed
    lists = [a for t, a in tools.calls if t == LIST]
    assert lists[0].get("cursor") == "2", lists


@pytest.mark.parametrize("code", ["INVALID_INPUT", "INVALID_ARGUMENTS"])
async def test_a_saved_page_the_system_no_longer_honours_restarts_the_listing(
    kb: httpx.AsyncClient, tools: FakeTools, code: str
) -> None:
    # A saved page goes stale: Salesforce drops a query locator after a while (INVALID_ARGUMENTS), and a sealed cursor
    # stops opening once its key changes (INVALID_INPUT). Resending it would fail every run from then on.
    src = await source(kb)
    tools.fail[f"{LIST}:2"] = "RATE_LIMITED"
    assert (await sync(kb, src["id"]))["status"] == "partial"
    tools.fail[f"{LIST}:2"] = code
    tools.calls.clear()
    resumed = await sync(kb, src["id"])
    assert resumed["status"] == "success", resumed
    lists = [a for t, a in tools.calls if t == LIST]
    assert lists[0].get("cursor") == "2" and not lists[1].get("cursor"), lists
    assert {"Reset a card PIN", "Report a lost card", "Travel notices"} <= set(await items(kb, src["id"]))


async def test_a_page_that_names_itself_again_ends_the_run(kb: httpx.AsyncClient, tools: FakeTools) -> None:
    src = await source(kb)
    tools.pages = "same"
    run = await sync(kb, src["id"])
    assert run["status"] == "partial", run
    assert len([a for t, a in tools.calls if t == LIST]) == 2, tools.calls


async def test_a_listing_stops_at_the_page_cap_and_continues_next_run(
    kb: httpx.AsyncClient, tools: FakeTools, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("ops_kb.tool_sources.MAX_PAGES", 3)
    src = await source(kb)
    tools.pages = "endless"
    run = await sync(kb, src["id"])
    assert run["status"] == "partial", run
    lists = [a for t, a in tools.calls if t == LIST]
    assert len(lists) == 3, lists
    tools.calls.clear()
    await sync(kb, src["id"])
    assert next(a for t, a in tools.calls if t == LIST).get("cursor") == "p3", tools.calls


async def test_a_refused_sign_in_pauses_until_the_connection_is_healthy(
    kb: httpx.AsyncClient, tools: FakeTools
) -> None:
    src = await source(kb)
    tools.fail[f"{LIST}:first"] = "AUTH_EXPIRED"
    tools.status = "needs_reconnect"
    run = await sync(kb, src["id"])
    assert run["status"] == "failed", run
    again = await kb.post(f"/v1/sources/{src['id']}/sync")
    assert again.status_code == 409 and again.json()["error"]["code"] == "needs_reconnect", again.text
    tools.status = "healthy"
    assert (await sync(kb, src["id"]))["status"] == "success"


async def test_a_connection_that_signs_in_each_person_cannot_be_a_source(
    kb: httpx.AsyncClient, tools: FakeTools
) -> None:
    tools.sign_in = "person"
    body = {"type": "tool", "name": "Mine", "config": {"plugin": "opsai.salesforce", "source": "articles"}}
    r = await kb.post("/v1/sources", json=body)
    assert r.status_code == 400 and "needs a team sign-in" in r.text, r.text


def test_a_daily_source_is_due_once_its_time_has_passed() -> None:
    s = {"status": "active", "config": {"schedule": {"kind": "daily", "time": "02:00"}}}
    now = datetime(2026, 10, 29, 3, 0, tzinfo=UTC)
    assert due({**s, "last_sync_at": None}, now)
    assert due({**s, "last_sync_at": datetime(2026, 10, 28, 3, 0, tzinfo=UTC)}, now)
    assert not due({**s, "last_sync_at": datetime(2026, 10, 29, 2, 30, tzinfo=UTC)}, now)
    assert not due({**s, "status": "paused", "last_sync_at": None}, now)


def test_with_plugins_off_kb_reaches_no_tool() -> None:
    # OPS_PLUGINS off until the plugins release: no gateway client, and no tools scope a kb token could claim.
    off = Settings(plugins=False, tools_url="http://tools.test")
    assert _tools_service(off) is None
    assert not {"tools:view", "tools:run"} & set(off.service_scopes["kb"])
    on = Settings(plugins=True, tools_url="http://tools.test")
    assert _tools_service(on) is not None
    assert {"tools:view", "tools:run"} <= set(on.service_scopes["kb"])
