"""Mock answers (c-332) through the real routes: a test call gets the first mock that matches its input or the default
and nothing reaches the system; a production call, or one that names no environment, never gets a mock; a delay and a
timeout wait no longer than the operation's limit; and changing mocks is tools.edit."""

from __future__ import annotations

from typing import Any

import httpx

from ops_tools.mocks import MAX_WAIT_MS, MockAnswers, chosen
from ops_tools.store.mocks import MockStore

from .conftest import service_headers
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_connections import admin, client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person

OP = f"{MODULE}_op1"


def _row(**kw: Any) -> dict[str, Any]:
    return {"match": {}, "is_default": False, **kw}


def test_the_first_match_in_order_answers_else_the_default() -> None:
    mocks = [
        _row(id="a", match={"accountId": "ERR"}),
        _row(id="b", match={"accountId": "ERR"}),
        _row(id="d", is_default=True),
    ]
    assert chosen(mocks, {"accountId": "ERR"})["id"] == "a"  # pyright: ignore[reportOptionalSubscript]
    assert chosen(mocks, {"accountId": "OK"})["id"] == "d"  # pyright: ignore[reportOptionalSubscript]
    assert chosen(mocks[:2], {"accountId": "OK"}) is None


async def test_a_wait_never_passes_the_operations_limit() -> None:
    waited: list[float] = []

    async def sleep(s: float) -> None:
        waited.append(s)

    answers = MockAnswers(MockStore(None), sleep)  # pyright: ignore[reportArgumentType]
    await answers.wait({"timeout": False, "delay_ms": 999_999}, 2000)
    await answers.wait({"timeout": True, "delay_ms": 0}, 1500)
    await answers.wait({"timeout": True, "delay_ms": 0}, 10_000_000)
    assert waited == [2.0, 1.5, MAX_WAIT_MS / 1000]


async def _mock(g: Gateway, body: dict[str, Any], who: dict[str, str] | None = None) -> httpx.Response:
    return await g.client.post(f"/v1/tool-modules/{MODULE}/operations/{OP}/mocks", json=body, headers=who or {})


async def _call(g: Gateway, args: dict[str, Any], step: str, environment: str | None) -> dict[str, Any]:
    context: dict[str, Any] = {"thread": g.thread, "step": step, "act": "agent:dispute_triage"}
    if environment is not None:
        context["environment"] = environment
    body = {"tool": g.tool("get_account"), "input": args, "key": step, "runContext": context}
    res = await g.client.post("/v1/calls", json=body, headers=service_headers(g.tenant))
    assert res.status_code == 200, res.text
    return res.json()["data"]


async def test_a_test_call_is_answered_from_its_mock_and_a_live_one_never(gateway: Gateway) -> None:  # noqa: F811
    g = gateway
    failing = {"name": "Core down", "match": {"accountId": "ERR-1"}, "status": 503, "body": {"error": "maintenance"}}
    assert (await _mock(g, failing)).status_code == 201
    sample = {
        "name": "Sample",
        "default": True,
        "body": {"accountId": "CHQ-0001", "balance": 10, "holder": {"sin": "1"}},
    }
    assert (await _mock(g, sample)).status_code == 201
    before = len(g.received)
    error = await _call(g, {"accountId": "ERR-1"}, "m1", "test")
    assert error["ok"] is False
    assert (error["output"]["error"]["code"], error["output"]["error"]["status"]) == ("UPSTREAM_ERROR", 503)
    default = await _call(g, {"accountId": "CHQ-9"}, "m2", "test")
    # A mock's answer is masked as the operation masks a real one.
    assert default["ok"] and default["output"]["holder"]["sin"] == "[redacted]"
    assert len(g.received) == before, "a mocked call reached the system"
    live = await _call(g, {"accountId": "ERR-1"}, "m3", "production")
    unsaid = await _call(g, {"accountId": "ERR-1"}, "m4", None)
    assert live["ok"] and unsaid["ok"], (live, unsaid)
    assert len(g.received) == before + 2


async def test_a_timeout_mock_fails_as_a_real_timeout(gateway: Gateway) -> None:  # noqa: F811
    g = gateway
    assert (await _mock(g, {"name": "Slow core", "match": {"accountId": "SLOW"}, "timeout": True})).status_code == 201
    out = await _call(g, {"accountId": "SLOW"}, "t1", "test")
    error = out["output"]["error"]
    assert (out["ok"], error["code"], error["side"]) == (False, "UPSTREAM_TIMEOUT", "upstream")


async def test_only_someone_who_edits_tools_changes_mocks(client: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    """On a seeded module, with people signed in on platform tokens: a viewer reads the mocks and cannot add one."""
    detail = (await client.get("/v1/tool-modules/mod_core_banking", headers=admin(tenant))).json()["data"]
    op = detail["operations"][0]
    path = f"/v1/tool-modules/mod_core_banking/operations/{op['id']}/mocks"
    viewer = person(tenant, "Victor Lang", {"team_platform": "viewer"})
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    refused = await client.post(path, json={"name": "x"}, headers=viewer)
    assert refused.status_code == 403, refused.text
    made = await client.post(path, json={"name": "x", "default": True}, headers=builder)
    assert made.status_code == 201, made.text
    listed = await client.get(path, headers=viewer)
    assert [m["name"] for m in listed.json()["data"]["data"]] == ["x"]
    unknown = await client.post(path, json={"name": "y", "match": {"colour": "red"}}, headers=builder)
    assert unknown.status_code == 400
