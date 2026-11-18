"""The shared service client, by failure mode: a token that does not name the caller's tenant, team and
scopes; an error whose status or code is lost on the way back; a read not retried after a dropped connection; a write
retried and run twice; a cursor list read only to its first page; a client built from settings that ignores the
callee's address, timeout or retries, or that calls this machine when the address is unset."""

from __future__ import annotations

import base64
import json
import socket
from typing import Any

import httpx
import pytest

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable, dev_service_signer
from ops_service_kit.narrow import a_list
from ops_service_kit.settings import Settings


def claims(request: httpx.Request) -> dict[str, Any]:
    token = request.headers["Authorization"].removeprefix("Bearer ")
    return json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))


def client(handler: Any, **kw: Any) -> ServiceClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://kb")
    return ServiceClient(http, dev_service_signer(), "agents", "kb", **kw)


async def test_each_call_names_the_callers_tenant_team_and_scopes() -> None:
    seen: list[dict[str, Any]] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(claims(r))
        return httpx.Response(200, json={"success": True, "data": [{"id": "kb_1"}]})

    c = client(handler, scopes=["knowledge:view"], tenant=lambda: "ten_a", team=lambda: "team_ops")
    assert await c.get("/v1/knowledge-bases/refs") == [{"id": "kb_1"}]
    await c.get("/v1/knowledge-bases/refs", team="team_fraud")
    await c.get("/v1/knowledge-bases/refs", tenant="ten_b", team="team_x")
    assert [(s["sub"], s["aud"], s["tenant_id"], s["team_id"], s["scopes"]) for s in seen] == [
        ("service:agents", "kb", "ten_a", "team_ops", ["knowledge:view"]),
        ("service:agents", "kb", "ten_a", "team_fraud", ["knowledge:view"]),
        ("service:agents", "kb", "ten_b", "team_x", ["knowledge:view"]),
    ]


async def test_an_error_keeps_the_callees_status_and_code() -> None:
    def handler(_r: httpx.Request) -> httpx.Response:
        error = {"code": "team_forbidden", "message": "kb_1 belongs to team_x", "status": 403}
        return httpx.Response(403, json={"success": False, "error": {**error, "details": {"teamId": "team_x"}}})

    with pytest.raises(ServiceCallError) as e:
        await client(handler).get("/v1/knowledge-bases/kb_1")
    assert (e.value.status, e.value.code, e.value.message, e.value.details) == (
        403,
        "team_forbidden",
        "kb_1 belongs to team_x",
        {"teamId": "team_x"},
    )


async def test_a_read_is_tried_once_more_after_a_dropped_connection_and_a_write_is_not() -> None:
    calls: list[str] = []

    def handler(r: httpx.Request) -> httpx.Response:
        calls.append(r.method)
        if len(calls) == 1 or r.method == "POST":
            raise httpx.ConnectError("reset")
        return httpx.Response(200, json={"success": True, "data": {"ok": True}})

    c = client(handler)
    assert await c.get("/v1/x") == {"ok": True}
    with pytest.raises(ServiceUnreachable):
        await c.post("/v1/x", {"a": 1})
    assert calls == ["GET", "GET", "POST"]


async def test_a_cursor_list_is_read_to_its_last_page() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        cursor = json.loads(r.content).get("cursor")
        page = {None: {"items": [1, 2], "nextLink": "c2"}, "c2": {"items": [3], "deltaLink": "d"}}[cursor]
        return httpx.Response(200, json={"success": True, "data": page})

    items = [
        i async for page in client(handler).pages("POST", "/v1/mailboxes/read") for i in a_list(page["items"], "items")
    ]
    assert items == [1, 2, 3]


async def test_a_success_that_is_not_json_is_an_error_and_an_empty_one_is_none() -> None:
    """A 200 with a body that is not JSON (a proxy's page) must not read as an empty answer: a caller treating
    "no value" as the default would act on it. A 204 has no body and answers None."""

    def page(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    def empty(_: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    garbled = client(page)
    with pytest.raises(ServiceCallError) as e:
        await garbled.get("/v1/policies/extractionFloor")
    assert (e.value.status, e.value.code) == (200, "bad_response")
    assert await client(empty).post("/v1/fences") is None


async def test_a_client_from_settings_calls_the_endpoint_with_its_timeout_and_retries() -> None:
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        closed = f"http://127.0.0.1:{taken.getsockname()[1]}"
    settings = Settings(auth_mode="dev", agents={"url": closed, "timeout_s": 3, "retries": 3})  # pyright: ignore[reportArgumentType]
    c = ServiceClient.for_settings(settings, service="kb", audience="agents", scopes=["agents:view"])
    sent: list[tuple[str, str, Any]] = []

    async def note(request: httpx.Request) -> None:
        sent.append((request.method, str(request.url), request.extensions["timeout"]["read"]))

    c.http.event_hooks["request"].append(note)
    try:
        for call in (c.get("/v1/agents"), c.post("/v1/events", json={})):
            with pytest.raises(ServiceUnreachable):
                await call
    finally:
        await c.aclose()
    # Nothing answers on the port: the read is tried once and three times more, the write once.
    assert sent == [("GET", f"{closed}/v1/agents", 3.0)] * 4 + [("POST", f"{closed}/v1/events", 3.0)]


def test_a_client_for_a_service_with_no_address_names_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPS_KB_URL", raising=False)
    monkeypatch.delenv("OPS_KB__URL", raising=False)
    with pytest.raises(ValueError, match="OPS_KB_URL is not set"):
        ServiceClient.for_settings(Settings(auth_mode="dev"), service="agents", audience="kb")
