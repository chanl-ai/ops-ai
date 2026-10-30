"""A plugin's data tools that page and build their query from checked inputs (c-581), by failure mode: a model's value
reaches the system unchecked or changes the query; an input used in the query is also sent as its own parameter; an
agent's call follows every page; a cursor is changed, comes from another tool, or names a host outside the plugin; a
page address from the system's answer names one of the tenant's secrets; and token and offset paging lose the query
they page through."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

import ops_tools.registry as reg
from ops_plugin_sdk.loader import Loaded
from ops_tools.executor import HttpExecutor
from ops_tools.graph_mailbox import CursorSeal
from ops_tools.plugins.executor import PluginExecutor
from ops_tools.plugins.host import PluginHost, module_of
from ops_tools.plugins.switches import InstallSwitches
from ops_tools.registry import ToolRegistry
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings

from .plugin_pager import plugin as pager
from .test_plugins import AllowAll, Policy

KEY = b"k" * 32
INSTANCE = "https://alpha.my.pager.test"
LINK_2 = "/api/query/01gPAGE2"


def answer(request: httpx.Request) -> httpx.Response:
    path, query = request.url.path, parse_qs(request.url.query.decode())
    if path == "/api/query":
        return httpx.Response(200, json={"records": [{"Id": "c1"}], "done": False, "nextRecordsUrl": LINK_2})
    if path == LINK_2:
        return httpx.Response(200, json={"records": [{"Id": "c2"}], "done": True})
    if path.startswith("/api/views/"):
        token = query.get("pageToken", [None])[0]
        return httpx.Response(200, json={"records": [{"id": token or "v1"}], "nextPageToken": None if token else "T2"})
    if path == "/api/search":
        offset = int(query.get("offset", ["0"])[0])
        rows = [{"Id": f"s{i}"} for i in range(3)][offset : offset + 2]
        return httpx.Response(200, json={"searchRecords": rows})
    return httpx.Response(404, json={"error": path})


class Rig:
    def __init__(self, engine: AsyncEngine, store: ModuleStore, tenant: str) -> None:
        self.seen: list[httpx.Request] = []

        def record(request: httpx.Request) -> httpx.Response:
            self.seen.append(request)
            return answer(request)

        switches = InstallSwitches(Policy({"test.pager": {"enabled": True}}))
        plugins = PluginHost(store, PluginBindings(engine), switches, [Loaded("pager", pager, None)])
        http = HttpExecutor(httpx.AsyncClient(transport=httpx.MockTransport(record)), AllowAll())  # type: ignore[arg-type]
        self.executor = PluginExecutor(plugins, http, KEY)
        self.tenant = tenant
        module = module_of(pager, tenant_id=tenant, at=datetime.now(UTC))
        self.ops = {o["name"]: o for o in module["operations"]}
        self.module = {
            "tenant_id": tenant,
            "id": module["id"],
            "display_name": "Pager",
            "template_id": "plugin:test.pager",
            "connection_id": "con_a",
            "endpoint": f"{INSTANCE}/api",
            "egress_hosts": ["alpha.my.pager.test"],
            "timeout_ms": 5000,
            "plugin_settings": {"instance_url": INSTANCE},
        }

    async def call(self, tool: str, args: dict[str, Any]) -> Any:
        op = self.ops[f"pager_{tool}"]
        return await self.executor.run(self.module, op, args, actor="t", environment=None, acting_for=None)

    def sent(self, i: int = -1) -> dict[str, list[str]]:
        return parse_qs(self.seen[i].url.query.decode())


@pytest.fixture
def rig(engine: AsyncEngine, store: ModuleStore, tenant: str) -> Rig:
    return Rig(engine, store, tenant)


def test_a_tool_that_pages_or_checks_its_inputs_runs_through_the_plugin_executor(rig: Rig) -> None:
    assert {rig.ops[f"pager_{t}"]["executor"] for t in ("find_cases", "list_view", "search")} == {"plugin"}
    cursor = next(f for f in rig.ops["pager_find_cases"]["input"] if f["name"] == "cursor")
    assert cursor["required"] is False


@pytest.mark.parametrize(
    "args",
    [
        {"status": "Escalated' OR Status != '"},
        {"status": "Escalated", "since": "yesterday"},
        {"status": "Escalated", "since": "2026-10-01T09:00:00Z' OR Id != '"},
    ],
)
async def test_a_value_its_input_does_not_allow_never_reaches_the_system(rig: Rig, args: dict[str, Any]) -> None:
    out = await rig.call("find_cases", args)
    assert not out.ok and out.output["error"]["code"] == "INVALID_INPUT", out
    assert rig.seen == []


async def test_a_quote_stays_inside_its_string_and_inputs_are_not_sent_twice(rig: Rig) -> None:
    out = await rig.call(
        "find_cases", {"status": "New", "since": "2026-10-01T11:00:00+02:00", "subject": "it's' OR Id != '"}
    )
    assert out.ok, out
    sent = rig.sent()
    assert sent["q"] == [
        "SELECT Id FROM Case WHERE Status = 'New' AND Subject != 'it\\'s\\' OR Id != \\'' "
        "AND LastModifiedDate > 2026-10-01T09:00:00Z"
    ], sent
    assert set(sent) == {"q"}, sent


async def test_an_agent_gets_one_page_and_a_sealed_cursor_for_the_next(rig: Rig) -> None:
    first = await rig.call("find_cases", {"status": "Escalated"})
    assert first.ok and [r["Id"] for r in first.output["records"]] == ["c1"], first
    cursor = first.output["next_cursor"]
    assert LINK_2 not in cursor and "nextRecordsUrl" not in first.output
    assert len(rig.seen) == 1
    second = await rig.call("find_cases", {"cursor": cursor})
    assert second.ok and [r["Id"] for r in second.output["records"]] == ["c2"], second
    assert rig.seen[-1].url.path == LINK_2 and rig.sent() == {}, rig.seen[-1].url
    assert "next_cursor" not in second.output


async def test_a_changed_cursor_or_one_from_another_tool_is_refused(rig: Rig) -> None:
    first = await rig.call("find_cases", {"status": "Escalated"})
    cursor = str(first.output["next_cursor"])
    other = CursorSeal(KEY, rig.tenant, "con_a", "pager_list_view").close(json.dumps({"link": LINK_2}))
    for bad in (cursor[:-2] + "xx", other):
        out = await rig.call("find_cases", {"cursor": bad})
        assert not out.ok and out.output["error"]["code"] == "INVALID_INPUT", out
    assert len(rig.seen) == 1


async def test_a_page_address_outside_the_plugins_hosts_is_refused(rig: Rig) -> None:
    seal = CursorSeal(KEY, rig.tenant, "con_a", "pager_find_cases")
    elsewhere = seal.close(json.dumps({"link": "https://evil.example/api/query/x"}))
    out = await rig.call("find_cases", {"cursor": elsewhere})
    assert not out.ok and out.output["error"]["code"] == "EGRESS_DENIED", out
    assert rig.seen == []


async def test_a_page_address_cannot_name_a_secret(rig: Rig) -> None:
    seal = CursorSeal(KEY, rig.tenant, "con_a", "pager_find_cases")
    # A system's answer is not trusted: `{{NAME}}` in its next address is sent as written, never resolved.
    named = seal.close(json.dumps({"link": "/api/query/{{OTHER_SYSTEM_KEY}}?x={{OTHER_SYSTEM_KEY}}"}))
    await rig.call("find_cases", {"cursor": named})
    sent = str(rig.seen[-1].url)
    assert "%7B%7BOTHER_SYSTEM_KEY%7D%7D" in sent and urlsplit(sent).hostname == "alpha.my.pager.test", sent


async def test_a_token_page_keeps_the_query_it_pages_through(rig: Rig) -> None:
    first = await rig.call("list_view", {"list_view": "00B000000000001"})
    assert first.ok and first.output["next_cursor"], first
    second = await rig.call("list_view", {"cursor": first.output["next_cursor"]})
    assert second.ok and second.output["records"] == [{"id": "T2"}], second
    assert rig.seen[-1].url.path == "/api/views/00B000000000001" and rig.sent() == {"pageToken": ["T2"]}
    assert "next_cursor" not in second.output


async def test_an_offset_page_ends_on_a_short_page(rig: Rig) -> None:
    first = await rig.call("search", {"q": "card*"})
    assert first.ok and len(first.output["searchRecords"]) == 2, first
    assert rig.sent()["q"] == ["FIND {card\\*}"] and rig.sent()["offset"] == ["0"] and rig.sent()["limit"] == ["2"]
    second = await rig.call("search", {"cursor": first.output["next_cursor"]})
    assert second.ok and second.output["searchRecords"] == [{"Id": "s2"}], second
    assert rig.sent()["offset"] == ["2"] and rig.sent()["q"] == ["FIND {card\\*}"]
    assert "next_cursor" not in second.output


class Keys:
    async def lookup(self, _tenant: str, _team: str | None, names: list[str], **_: Any) -> dict[str, str]:
        return dict.fromkeys(names, "s3cr3t-value")


def echo_key(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"echo": request.headers.get("X-Key"), "nextRecordsUrl": "/x"})


async def test_the_answer_hook_sees_the_answer_only_after_secrets_are_scrubbed() -> None:
    http = HttpExecutor(httpx.AsyncClient(transport=httpx.MockTransport(echo_key)), AllowAll(), Keys())  # type: ignore[arg-type]
    op = {"name": "get", "method": "GET", "path": "/thing", "headers": [{"key": "X-Key", "value": "{{API_KEY}}"}]}
    module = {
        "tenant_id": "t",
        "endpoint": f"{INSTANCE}/api",
        "egress_hosts": ["alpha.my.pager.test"],
        "timeout_ms": 5000,
    }
    seen: list[Any] = []
    out = await http.run(module, op, {}, on_answer=lambda a: seen.append(a) or a)
    assert out.ok and seen and "s3cr3t-value" not in json.dumps(seen), seen


async def test_a_failing_answer_hook_fails_the_call_cleanly() -> None:
    http = HttpExecutor(httpx.AsyncClient(transport=httpx.MockTransport(echo_key)), AllowAll())  # type: ignore[arg-type]
    module = {
        "tenant_id": "t",
        "endpoint": f"{INSTANCE}/api",
        "egress_hosts": ["alpha.my.pager.test"],
        "timeout_ms": 5000,
    }

    def broken(_: Any) -> Any:
        raise KeyError("next")

    out = await http.run(module, {"name": "get", "method": "GET", "path": "/thing"}, {}, on_answer=broken)
    assert not out.ok and out.output["error"]["code"] == "ANSWER_UNREADABLE", out


async def test_a_plugin_tools_title_is_listed_with_it(
    local_catalog: Any, engine: AsyncEngine, store: ModuleStore, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindings = PluginBindings(engine)
    await bindings.put(tenant, "team_a", "test.pager", enabled=True, connection_id="con_a", settings={}, by="t")
    switches = InstallSwitches(Policy({"test.pager": {"enabled": True}}))
    plugins = PluginHost(store, bindings, switches, [Loaded("pager", pager, None)])
    monkeypatch.setattr(reg, "acting_team", lambda: "team_a")
    rows = {t["name"]: t for t in await ToolRegistry(local_catalog, store, plugins).grantable(tenant)}
    assert rows["pager_find_cases"]["title"] == "Find cases", rows.get("pager_find_cases")


async def test_the_next_page_needs_only_its_cursor_and_a_first_page_its_required_inputs(rig: Rig) -> None:
    # The gateway checks a call against the operation's inputs before the plugin executor runs: a next-page call
    # carrying only the cursor was refused for the status it does not need.
    status = next(f for f in rig.ops["pager_find_cases"]["input"] if f["name"] == "status")
    assert status["required"] is False, status
    missing = await rig.call("find_cases", {})
    assert not missing.ok and "status" in missing.output["error"]["message"], missing
    assert rig.seen == []
