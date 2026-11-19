"""The /v1/workflows routes by failure mode: a reply, status or error code changing as the routes move onto the kit's
models and the request transaction; a route reading only this service's rows taking a connection per store call, so
one answer mixes rows from different moments; a connection held while platform-service or the model answers; and a
list whose equal sort values let a row repeat or go missing across pages. Regenerate the pins only for an intended
change: `AGENTS_REPIN=1` writes what the routes answer now to `fixtures/reply-pins-workflows.json`."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.pool import Pool

from ops_agents.api.routers import workflows
from ops_agents.graphs.definition import compile_definition
from ops_identity import dev_service_signer, mint_service_token

from .test_reply_pins import FIXTURES, answer, compare
from .test_workflow_registry import EMAIL

# Marks a row sent as tools-service. Its token is minted per request: it lives 60 seconds, and a suite reaches this
# file later than that after import.
TOOLS = object()
APPROVAL = {"name": "Payee check", "trigger": "Payee added", "template": "approval", "agentSlug": "wire-fraud-sentinel"}

# (name, method, path, body): `{wid}` is the workflow the first row creates. Each answered value by value, in order.
PINNED: list[tuple[str, str, str, Any]] = [
    ("create", "post", "/v1/workflows", APPROVAL),
    ("create.unknownField", "post", "/v1/workflows", {"name": "X", "colour": "red"}),
    ("create.badTemplate", "post", "/v1/workflows", {"name": "X", "template": "nope"}),
    ("create.chatNoAgent", "post", "/v1/workflows", {"name": "X", "template": "chat"}),
    ("list", "get", "/v1/workflows?pageSize=3", None),
    ("list.desc", "get", "/v1/workflows?sortBy=name&sortOrder=desc&pageSize=3", None),
    ("list.pastEnd", "get", "/v1/workflows?page=99&pageSize=10", None),
    ("list.pageSizeOver", "get", "/v1/workflows?pageSize=201", None),
    ("list.draft", "get", "/v1/workflows?status=draft", None),
    ("list.current", "get", "/v1/workflows?engine=current", None),
    ("list.startable", "get", "/v1/workflows?startable=true&pageSize=3", None),
    ("routeFields", "get", "/v1/workflows/route-fields", None),
    ("read", "get", "/v1/workflows/{wid}", None),
    ("read.missing", "get", "/v1/workflows/wf_missing", None),
    ("settings", "patch", "/v1/workflows/{wid}", {"description": "Checks a new payee."}),
    ("settings.unknownField", "patch", "/v1/workflows/{wid}", {"owner": "me"}),
    ("live.unpublished", "post", "/v1/workflows/{wid}/status", {"status": "live"}),
    ("validate", "post", "/v1/workflows/{wid}/validate", {"graph": {"nodes": [], "edges": []}}),
    ("validations.latest", "get", "/v1/workflows/{wid}/validations/latest", None),
    ("test", "post", "/v1/workflows/{wid}/test", {"email": EMAIL}),
    ("publish.notCompiling", "post", "/v1/workflows/{wid}/publish-requests", {"graph": {"nodes": [], "edges": []}}),
    ("publish", "post", "/v1/workflows/{wid}/publish-requests", "draft"),
    ("versions", "get", "/v1/workflows/{wid}/versions", None),
    ("restore", "post", "/v1/workflows/{wid}/versions/1/restore", None),
    ("restore.missing", "post", "/v1/workflows/{wid}/versions/9/restore", None),
    ("saveDraft", "put", "/v1/workflows/{wid}/draft", {"graph": {"nodes": [], "edges": []}}),
    ("discardDraft", "delete", "/v1/workflows/{wid}/draft", None),
    ("pointer", "post", "/v1/workflows/{wid}/pointer", {"version": 1}),
    ("pointer.missing", "post", "/v1/workflows/{wid}/pointer", {"version": 9}),
    ("status", "post", "/v1/workflows/{wid}/status", {"status": "paused"}),
    ("runs", "get", "/v1/workflows/{wid}/runs", None),
    ("runs.pastEnd", "get", "/v1/workflows/{wid}/runs?page=5&pageSize=2", None),
    ("refs.service", "get", "/v1/workflow-refs", TOOLS),
    ("delete", "delete", "/v1/workflows/{wid}", None),
    ("delete.again", "delete", "/v1/workflows/{wid}", None),
]


async def _send(client: AsyncClient, method: str, path: str, body: Any, wid: str) -> Any:
    url = path.replace("{wid}", wid)
    if body is TOOLS:
        token = mint_service_token(
            dev_service_signer(), service="tools", audience="agents", tenant_id="local", scopes=["workflows:view"]
        )
        return await client.request(method, url, headers={"Authorization": f"Bearer {token}"})
    if body == "draft":
        body = {"graph": (await client.get(f"/v1/workflows/{wid}")).json()["data"]["draft"]["graph"], "note": "go"}
    return await client.request(method, url, json=body) if body is not None else await client.request(method, url)


async def test_the_workflow_routes_keep_every_key_value_and_error_object(client: AsyncClient) -> None:
    seen: dict[str, Any] = {}
    wid = ""
    for name, method, path, body in PINNED:
        r = await _send(client, method, path, body, wid)
        wid = wid or r.json()["data"]["id"]
        seen[name] = answer(r)
    # An error message names the generated id.
    compare(json.loads(json.dumps(seen).replace(wid, "<wf>")), FIXTURES / "reply-pins-workflows.json")


@contextmanager
def _held_by_request() -> Generator[Callable[[], int]]:
    """How many connections the request's own task holds right now; the app's loops check out connections too."""
    task = asyncio.current_task()
    held: set[int] = set()

    def out(_conn: object, record: object, _proxy: object) -> None:
        if asyncio.current_task() is task:
            held.add(id(record))

    def back(_conn: object, record: object) -> None:
        held.discard(id(record))

    event.listen(Pool, "checkout", out)
    event.listen(Pool, "checkin", back)
    try:
        yield lambda: len(held)
    finally:
        event.remove(Pool, "checkout", out)
        event.remove(Pool, "checkin", back)


# (method, path, body, connections the request checks out). One: the route answers in the request transaction. Zero:
# it reads nothing from the database. More: it asks another party, so each read takes its own connection.
CHECKOUTS: list[tuple[str, str, Any, int]] = [
    ("get", "/v1/workflows", None, 1),
    ("get", "/v1/workflows/route-fields", None, 0),
    ("patch", "/v1/workflows/{wid}", {"description": "Checks a new payee."}, 1),
    ("post", "/v1/workflows/{wid}/validate", {"graph": {"nodes": [], "edges": []}}, 1),
    ("get", "/v1/workflows/{wid}/validations/latest", None, 1),
    ("put", "/v1/workflows/{wid}/draft", {"graph": {"nodes": [], "edges": []}}, 1),
    ("delete", "/v1/workflows/{wid}/draft", None, 1),
    ("get", "/v1/workflows/{wid}/versions", None, 1),
    ("post", "/v1/workflows/{wid}/status", {"status": "paused"}, 1),
    ("get", "/v1/workflows/{wid}/runs", None, 1),
    ("get", "/v1/workflow-refs", TOOLS, 1),
    ("post", "/v1/workflows", {"name": "Second"}, 1),
    ("delete", "/v1/workflows/{wid}", None, 1),
]


async def test_each_workflow_route_checks_out_the_connections_it_should(client: AsyncClient) -> None:
    wid = (await client.post("/v1/workflows", json=APPROVAL)).json()["data"]["id"]
    request_task = asyncio.current_task()
    counted: list[int] = []

    def checked_out(*_: object) -> None:
        if asyncio.current_task() is request_task:
            counted[-1] += 1

    event.listen(Pool, "checkout", checked_out)
    seen: list[tuple[str, int, int]] = []
    try:
        for method, path, body, _ in CHECKOUTS:
            counted.append(0)
            r = await _send(client, method, path, body, wid)
            seen.append((f"{method} {path}", r.status_code // 100, counted[-1]))
    finally:
        event.remove(Pool, "checkout", checked_out)
    assert seen == [(f"{m} {p}", 2, n) for m, p, _, n in CHECKOUTS], "\n".join(map(str, seen))


class _WatchedRun:
    """A compiled test-run graph that notes what the request holds each time it runs the model."""

    def __init__(self, inner: Any, held: Callable[[], int], seen: list[int]) -> None:
        self.inner, self.held, self.seen = inner, held, seen

    async def ainvoke(self, *args: Any) -> Any:
        self.seen.append(self.held())
        return await self.inner.ainvoke(*args)

    async def aget_state(self, config: Any) -> Any:
        return await self.inner.aget_state(config)


async def test_no_connection_is_held_while_a_workflow_route_asks_another_party(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read names its team from platform-service, the publish reads the team's publish policy and review deadline
    there, and the test run runs the model: none of them with a connection held."""
    wid = (await client.post("/v1/workflows", json=APPROVAL)).json()["data"]["id"]
    draft = (await client.get(f"/v1/workflows/{wid}")).json()["data"]["draft"]["graph"]
    seen: dict[str, list[int]] = {}
    with _held_by_request() as held:

        def watched(name: str) -> None:
            real = getattr(workflows, name)

            async def asked(*args: Any, **kwargs: Any) -> Any:
                seen.setdefault(name, []).append(held())
                return await real(*args, **kwargs)

            monkeypatch.setattr(workflows, name, asked)

        for name in ("team_name", "decide", "sla_hours"):
            watched(name)
        compile_real = compile_definition
        runs = seen.setdefault("model", [])

        def compiled(*args: Any) -> _WatchedRun:
            return _WatchedRun(compile_real(*args), held, runs)

        monkeypatch.setattr(workflows, "compile_definition", compiled)
        codes = [
            (await client.get(f"/v1/workflows/{wid}")).status_code,
            (await client.post(f"/v1/workflows/{wid}/test", json={"email": EMAIL})).status_code,
            (await client.post(f"/v1/workflows/{wid}/publish-requests", json={"graph": draft})).status_code,
        ]
    assert codes == [200, 200, 201]
    assert {k: set(v) for k, v in seen.items()} == {k: {0} for k in ("team_name", "model", "decide", "sla_hours")}


async def test_workflows_with_one_name_page_without_repeating_or_skipping(client: AsyncClient) -> None:
    made = {(await client.post("/v1/workflows", json={"name": "Same"})).json()["data"]["id"] for _ in range(3)}
    pages = [
        (
            await client.get(
                "/v1/workflows",
                params={"search": "same", "pageSize": 1, "page": p, "sortBy": "name", "sortOrder": "desc"},
            )
        ).json()["data"]
        for p in (1, 2, 3)
    ]
    ids = [row["id"] for p in pages for row in p["data"]]
    # Equal names fall back to the id, in the list's order.
    assert ids == sorted(made, reverse=True), ids
    assert pages[0]["pagination"]["total"] == 3
