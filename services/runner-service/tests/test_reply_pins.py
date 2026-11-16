"""Pins runner-service's wire format as tools-service sees it: each route's status, reply keys and values, the body
names it accepts, and the call a run makes back to tools-service for each `ops.call`. A change that alters any of them
fails here, whatever the models behind them become."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
from fastapi.testclient import TestClient

from ops_identity import ServiceClient, dev_service_signer, mint_service_token
from ops_runner.app import create_runner_app
from ops_runner.wasm import WasmPython
from ops_service_kit.settings import Settings


def service(team: str | None = "team-a") -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="tools", audience="runner", tenant_id="local", team_id=team, ttl_s=3600
    )
    return {"Authorization": f"Bearer {token}"}


def client(runtime: WasmPython, tools: ServiceClient | None = None) -> TestClient:
    settings = Settings(environment="dev", runner_concurrency=3)
    return TestClient(create_runner_app(runtime, settings=settings, tools=tools))


def claims(request: httpx.Request) -> dict[str, Any]:
    payload = request.headers["authorization"].removeprefix("Bearer ").split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def test_health_answers_its_status_and_capacity(runtime: WasmPython) -> None:
    r = client(runtime).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "running": 0, "capacity": 3}


def test_a_run_answers_every_reply_key(runtime: WasmPython) -> None:
    r = client(runtime).post(
        "/v1/runs", json={"source": "def main(i):\n    print('hi')\n    return [i, 2]", "input": 1}, headers=service()
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"success", "data"} and body["success"] is True
    data = body["data"]
    assert set(data) == {"ok", "output", "error", "log", "calls", "createMs", "executeMs", "trace"}
    assert (data["ok"], data["output"], data["error"], data["log"], data["calls"], data["trace"]) == (
        True,
        [1, 2],
        None,
        "hi\n",
        0,
        [],
    )
    assert isinstance(data["createMs"], int) and isinstance(data["executeMs"], int)


def test_a_failed_run_answers_its_error_code_and_message(runtime: WasmPython) -> None:
    r = client(runtime).post("/v1/runs", json={"source": "def main(i):\n    return 1 / 0"}, headers=service())
    data = r.json()["data"]
    assert r.status_code == 200 and data["ok"] is False and data["output"] is None
    assert data["error"] == {"code": "function_error", "message": "ZeroDivisionError: division by zero"}


def test_the_body_takes_camel_and_snake_names_and_refuses_others(runtime: WasmPython) -> None:
    c = client(runtime)
    source = "def run(i):\n    return i"
    for body in (
        {"source": source, "entry": "run", "input": 5, "callToken": None, "limits": {"memoryMb": 64, "timeS": 5}},
        {"source": source, "entry": "run", "input": 5, "call_token": None, "limits": {"memory_mb": 64, "calls": 1}},
    ):
        r = c.post("/v1/runs", json=body, headers=service())
        assert r.status_code == 200 and r.json()["data"]["output"] == 5, r.text
    for body in ({"source": source, "language": "python"}, {"source": source, "limits": {"cpu": 1}}, {"source": ""}):
        r = c.post("/v1/runs", json=body, headers=service())
        assert r.status_code == 400 and r.json()["success"] is False, (body, r.text)


def test_each_call_goes_to_tools_service_as_the_runs_tenant_and_team(runtime: WasmPython) -> None:
    seen: list[httpx.Request] = []

    async def tools_service(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        tool = json.loads(request.content)["tool"]
        if tool == "lookup":
            return httpx.Response(200, json={"success": True, "data": {"ok": True, "output": {"n": 7}}})
        if tool == "denied":
            error = {"code": "forbidden", "message": "Not yours.", "status": 403}
            return httpx.Response(403, json={"success": False, "error": error})
        raise httpx.ConnectError("refused", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(tools_service), base_url="http://tools.test")
    tools = ServiceClient(http, dev_service_signer(), "runner", "tools", ["tools:run"])
    source = (
        "def main(i):\n"
        "    out = [ops.call('lookup', {'q': ops.secret('KEY')})]\n"
        "    for name in ('denied', 'down'):\n"
        "        try:\n"
        "            ops.call(name)\n"
        "        except OpsError as e:\n"
        "            out.append([e.code, e.message])\n"
        "    return out"
    )
    r = client(runtime, tools).post("/v1/runs", json={"source": source, "callToken": "ct-1"}, headers=service())
    data = r.json()["data"]
    assert data["output"] == [{"n": 7}, ["forbidden", "Not yours."], ["call_failed", "The gateway did not answer."]]
    assert data["calls"] == 3
    assert data["trace"] == [
        {"tool": "lookup", "ok": True, "code": None},
        {"tool": "denied", "ok": False, "code": "forbidden"},
        {"tool": "down", "ok": False, "code": "call_failed"},
    ]
    first = seen[0]
    assert (first.method, first.url.path) == ("POST", "/v1/code-runs/calls")
    assert json.loads(first.content) == {"tool": "lookup", "input": {"q": {"$secret": "KEY"}}}
    assert first.headers["x-code-run"] == "ct-1"
    token = claims(first)
    assert (token["sub"], token["aud"], token["tenant_id"], token["team_id"]) == (
        "service:runner",
        "tools",
        "local",
        "team-a",
    )
