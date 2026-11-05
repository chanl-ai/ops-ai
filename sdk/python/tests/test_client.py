"""The hand-written layer, by failure mode, against httpx's mock transport: a call that loses the key or the team, a
caller who sees the envelope instead of the data, a refusal that loses the API's code or request id, a list that
stops after its first page for either paging shape, a write retried without an idempotency key, and a wait that hangs
on a run stopped at a human task."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from ops_ai import AsyncOpsAI, Conflict, NotFound, OpsAI, OpsError

BASE = "https://ops.test"


def client(handler: Any, **kw: Any) -> OpsAI:
    return OpsAI(
        api_key="ok_test", base_url=BASE, team="team_a", http=httpx.Client(transport=httpx.MockTransport(handler)), **kw
    )


def ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": data})


def test_every_call_carries_the_key_and_team_and_returns_the_data() -> None:
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return ok({"id": "ag_1", "name": "Dispute Desk"})

    agent = client(handler).agents.get("ag_1")
    assert agent == {"id": "ag_1", "name": "Dispute Desk"}
    r = seen[0]
    assert str(r.url) == f"{BASE}/api/agents/v1/agents/ag_1"
    assert (r.headers["x-api-key"], r.headers["x-team-id"]) == ("ok_test", "team_a")


def test_a_refusal_raises_its_class_with_the_code_and_request_id() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        body = {
            "success": False,
            "error": {"code": "not_found", "message": "No such agent", "status": 404, "requestId": "req_9"},
        }
        return httpx.Response(404, json=body)

    with pytest.raises(NotFound) as e:
        client(handler).agents.get("ag_x")
    assert (e.value.code, e.value.request_id, e.value.status) == ("not_found", "req_9", 404)


def test_a_list_walks_every_page_in_both_paging_shapes() -> None:
    def handler(r: httpx.Request) -> httpx.Response:
        page = int(r.url.params.get("page", "1"))
        if r.url.path.endswith("/v1/agents"):
            return ok({"items": [f"a{page}"], "pagination": {"page": page, "hasNext": page < 3}})
        cursor = r.url.params.get("cursor")
        return ok({"items": ["t2"]} if cursor else {"items": ["t1"], "nextCursor": "c2"})

    c = client(handler)
    assert list(c.agents.list()) == ["a1", "a2", "a3"]
    pages = c.raw.agents.agents_tool_options()
    assert pages["nextCursor"] == "c2"


def test_a_read_is_retried_and_a_write_without_a_key_is_not() -> None:
    calls: dict[str, int] = {"GET": 0, "POST": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        calls[r.method] += 1
        if calls[r.method] == 1:
            return httpx.Response(503, json={"success": False, "error": {"code": "unavailable", "message": "busy"}})
        return ok({"id": "x"})

    c = client(handler)
    c.config.max_retries = 1
    assert c.agents.get("ag_1") == {"id": "x"}
    with pytest.raises(OpsError):
        c.agents.create({"name": "x"})
    assert calls == {"GET": 2, "POST": 1}


def test_wait_returns_at_a_human_task_with_its_id_then_decide_finishes_the_run() -> None:
    state = {"status": "running", "polls": 0}

    def handler(r: httpx.Request) -> httpx.Response:
        if r.method == "POST" and r.url.path.endswith("/decision"):
            assert json.loads(r.content) == {"decision": "approve"}
            state["status"] = "succeeded"
            return ok({"id": "rv_1", "status": "approved"})
        state["polls"] += 1
        if state["status"] == "running" and state["polls"] > 1:
            state["status"] = "waiting"
        waiting = (
            {"node": "approve", "iteration": 0, "payload": {"review_id": "rv_1"}}
            if state["status"] == "waiting"
            else None
        )
        return ok({"id": "run_1", "status": state["status"], "waiting": waiting})

    c = client(handler)
    run = c.runs.wait("run_1", interval=0)
    assert (run["status"], run["taskId"]) == ("waiting", "rv_1")
    c.tasks.decide(run["taskId"], "approve")
    assert c.runs.wait("run_1", interval=0)["status"] == "succeeded"


def test_the_async_client_unwraps_and_raises_the_same_way() -> None:

    def handler(r: httpx.Request) -> httpx.Response:
        if r.method == "POST":
            return httpx.Response(
                409, json={"success": False, "error": {"code": "already_decided", "message": "Decided"}}
            )
        return ok({"id": "rv_1"})

    async def run() -> None:
        async with AsyncOpsAI(
            api_key="k", base_url=BASE, http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ) as c:
            assert await c.tasks.get("rv_1") == {"id": "rv_1"}
            with pytest.raises(Conflict):
                await c.tasks.decide("rv_1", "approve")

    asyncio.run(run())


def test_a_person_token_from_the_profile_or_ops_token_acts_as_that_person(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A workflow is edited by a person, never by an API key, so a token the profile or OPS_TOKEN holds is who
    # the call acts as, even beside a key.
    seen: list[httpx.Request] = []

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        return ok({"id": "ag_1"})

    profile = {"baseUrl": BASE, "team": "team_a", "apiKey": "ok_test", "accessToken": "person_from_profile"}
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"current": "local", "profiles": {"local": profile}}))
    monkeypatch.setenv("OPS_CONFIG", str(config))
    monkeypatch.delenv("OPS_API_KEY", raising=False)
    monkeypatch.delenv("OPS_TOKEN", raising=False)
    http = httpx.Client(transport=httpx.MockTransport(handler))
    OpsAI(profile="local", http=http).agents.get("ag_1")
    monkeypatch.setenv("OPS_TOKEN", "person_from_env")
    OpsAI(profile="local", http=http).agents.get("ag_1")
    got = [(r.headers.get("authorization"), r.headers.get("x-api-key")) for r in seen]
    assert got == [("Bearer person_from_profile", None), ("Bearer person_from_env", None)], got


def _session_handler(seen: list[httpx.Request]) -> Any:
    """A platform that signs in with token t1, refuses t1 once its roles changed, and renews r1 to t2 exactly once."""

    def handler(r: httpx.Request) -> httpx.Response:
        seen.append(r)
        if r.url.path.endswith("/v1/auth/sign-in"):
            return ok({"token": "t1", "refreshToken": "r1", "expiresAt": "x", "principal": {}})
        if r.url.path.endswith("/v1/auth/refresh"):
            if json.loads(r.content)["refreshToken"] != "r1":
                return httpx.Response(401, json={"success": False, "error": {"code": "unauthorized", "message": "x"}})
            return ok({"token": "t2", "refreshToken": "r2", "expiresAt": "x", "principal": {}})
        if r.headers.get("authorization") == "Bearer t1":
            error = {"code": "permissions_changed", "message": "Your roles changed.", "status": 401}
            return httpx.Response(401, json={"success": False, "error": error})
        return ok({"id": "ag_1"})

    return handler


def test_a_signed_in_client_renews_once_when_its_roles_changed_and_retries() -> None:
    seen: list[httpx.Request] = []
    ops = OpsAI.sign_in(
        "james@bank.example",
        "pw",
        base_url=BASE,
        team="team_a",
        http=httpx.Client(transport=httpx.MockTransport(_session_handler(seen))),
    )
    assert ops.agents.get("ag_1") == {"id": "ag_1"}
    # Another team's client shares the renewed session: a refresh token works once, so it is never spent twice.
    assert ops.with_team("team_b").agents.get("ag_1") == {"id": "ag_1"}
    assert [r.url.path for r in seen].count("/api/platform/v1/auth/refresh") == 1
    assert seen[-1].headers["authorization"] == "Bearer t2"


def test_the_async_client_renews_the_same_way() -> None:
    seen: list[httpx.Request] = []

    async def run() -> Any:
        ops = await AsyncOpsAI.sign_in(
            "james@bank.example",
            "pw",
            base_url=BASE,
            team="team_a",
            http=httpx.AsyncClient(transport=httpx.MockTransport(_session_handler(seen))),
        )
        return await ops.agents.get("ag_1")

    assert asyncio.run(run()) == {"id": "ag_1"}
    assert seen[-1].headers["authorization"] == "Bearer t2"
