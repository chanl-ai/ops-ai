"""`ops plugin test` runs a paged data tool the way tools-service does, by failure mode: the runner sends a query value
unchecked, so a plugin's tests pass where tools-service refuses the call; it follows every page, or loses the query
on the next one; or it follows a page address to a host the plugin does not list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from test_query_inputs import PAGED, with_tools
from test_validate import plugin

from ops_plugin_sdk import EgressDenied, Plugin
from ops_plugin_sdk.formats import InputRefused
from ops_plugin_sdk.testing import Fake, call

SETTINGS = {"instance_url": "https://alpha.my.desk.test"}


def answer(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/v1/query":
        return httpx.Response(200, json={"records": [{"Id": "c1"}], "nextRecordsUrl": "/api/v1/query/01g2"})
    if request.url.path == "/api/v1/query/01g2":
        return httpx.Response(200, json={"records": [{"Id": "c2"}]})
    return httpx.Response(404)


@pytest.fixture
def run(tmp_path: Path) -> tuple[Plugin, Fake, list[httpx.Request]]:
    root = plugin(tmp_path, with_tools(PAGED))
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answer(request)

    return (
        Plugin.beside(str(root / "__init__.py")),
        Fake(httpx.Client(transport=httpx.MockTransport(record)), "t"),
        seen,
    )


def test_a_paged_tool_answers_one_page_and_a_cursor_that_reads_the_next(
    run: tuple[Plugin, Fake, list[httpx.Request]],
) -> None:
    p, fake, seen = run
    first = call(p, "find_cases", {"status": "New", "since": "2026-10-01T09:00:00Z"}, SETTINGS, fake)
    assert first["records"] == [{"Id": "c1"}] and "nextRecordsUrl" not in first and len(seen) == 1
    q = seen[0].url.params["q"]
    assert (
        "Status = 'New'" in q and "LastModifiedDate > 2026-10-01T09:00:00Z" in q and "status" not in seen[0].url.params
    )
    second = call(p, "find_cases", {"cursor": first["next_cursor"]}, SETTINGS, fake)
    assert second == {"records": [{"Id": "c2"}]} and seen[1].url.path == "/api/v1/query/01g2"
    assert dict(seen[1].url.params) == {}


def test_a_value_its_input_does_not_allow_is_refused_before_any_request(
    run: tuple[Plugin, Fake, list[httpx.Request]],
) -> None:
    p, fake, seen = run
    with pytest.raises(InputRefused, match="status must be one of"):
        call(p, "find_cases", {"status": "New' OR Id != '"}, SETTINGS, fake)
    assert seen == []


def test_a_page_address_on_another_host_is_refused(run: tuple[Plugin, Fake, list[httpx.Request]]) -> None:
    p, fake, seen = run
    cursor: dict[str, Any] = {"link": "https://evil.example/api/v1/query/x", "args": {"status": "New"}}
    with pytest.raises(EgressDenied):
        call(p, "find_cases", {"cursor": json.dumps(cursor)}, SETTINGS, fake)
    assert seen == []


HEADER_PAGED = """
  - name: issues
    access: read
    input: { state: { type: string, enum: [open, all], required: false, default: open } }
    request:
      method: GET
      path: /issues
      query: { state: "{{state}}" }
      paging: { rule: link_header }
  - name: pages
    access: read
    input: { state: { type: string, enum: [open, all] } }
    request:
      method: GET
      path: /pages
      query: { state: "{{state}}" }
      paging: { rule: page, limit: 2, limit_param: per_page }
"""
ISSUES_2 = "https://alpha.my.desk.test/api/v1/issues?state=open&page=2"


def numbered(request: httpx.Request) -> httpx.Response:
    q = request.url.params
    if request.url.path == "/api/v1/issues":
        if q.get("page") is None:
            nxt = "https://evil.example/x" if q.get("state") == "all" else ISSUES_2
            return httpx.Response(200, json=[{"n": 1}], headers={"Link": f'<{nxt}>; rel="next"'})
        return httpx.Response(200, json=[{"n": 2}])
    page, size = int(q["page"]), int(q["per_page"])
    return httpx.Response(200, json=[{"p": i} for i in range(1, 4)][(page - 1) * size : page * size])


@pytest.fixture
def header_run(tmp_path: Path) -> tuple[Plugin, Fake, list[httpx.Request]]:
    root = plugin(tmp_path, with_tools(HEADER_PAGED))
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return numbered(request)

    return (
        Plugin.beside(str(root / "__init__.py")),
        Fake(httpx.Client(transport=httpx.MockTransport(record)), "t"),
        seen,
    )


def test_a_link_header_page_follows_rel_next_and_only_to_the_plugins_hosts(
    header_run: tuple[Plugin, Fake, list[httpx.Request]],
) -> None:
    p, fake, seen = header_run
    first = call(p, "issues", {}, SETTINGS, fake)
    assert first["records"] == [{"n": 1}] and first["next_cursor"], first
    second = call(p, "issues", {"cursor": first["next_cursor"]}, SETTINGS, fake)
    assert second == [{"n": 2}] and str(seen[-1].url) == ISSUES_2
    elsewhere = call(p, "issues", {"state": "all"}, SETTINGS, fake)
    with pytest.raises(EgressDenied):
        call(p, "issues", {"cursor": elsewhere["next_cursor"]}, SETTINGS, fake)


def test_a_numbered_page_keeps_its_query_and_ends_on_a_short_page(
    header_run: tuple[Plugin, Fake, list[httpx.Request]],
) -> None:
    p, fake, seen = header_run
    first = call(p, "pages", {"state": "all"}, SETTINGS, fake)
    assert first["records"] == [{"p": 1}, {"p": 2}]
    assert dict(seen[-1].url.params) == {"state": "all", "page": "1", "per_page": "2"}
    second = call(p, "pages", {"cursor": first["next_cursor"]}, SETTINGS, fake)
    assert second == [{"p": 3}] and dict(seen[-1].url.params) == {"state": "all", "page": "2", "per_page": "2"}
