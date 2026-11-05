"""The test console's Real target: a read or a write is the real call the gateway would make, a real
write is logged under the person who sent it, and Mock sends nothing. One test per way the panel could claim a call it
did not make, or make a call nobody approved."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .test_apply_tool_access import apply_access
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

BASE = f"/v1/tool-modules/{MODULE}"


@pytest.fixture
async def g(gateway: Gateway) -> Gateway:  # noqa: F811
    return gateway


SECURITY = {"X-Dev-User": "Nadia Petrov"}
# The team the console acts in, sent with every request as the console sends it: a Real run is a gateway call made in
# the person's acting team, which owns the bank module.
TEAM = {"X-Team-Id": "team_platform"}


async def _context(g: Gateway) -> dict[str, Any]:
    """A run context to test as: a workflow approved for the bank module's operations, decided by a second person."""
    request = {
        "workflowId": "wf_dispute",
        "environment": "production",
        "operations": [g.tool("get_account"), g.tool("place_hold"), g.tool("limited")],
        "expiresInDays": 30,
        "justification": "Reads for the test console",
    }
    approval = await g.client.post(f"{BASE}/approvals", json=request)
    assert approval.status_code == 201, approval.text
    decided = await apply_access(g.client, g.tenant, {**approval.json()["data"], "moduleId": MODULE})
    assert decided.status_code == 200 and decided.json()["data"]["ok"], decided.text
    contexts: list[dict[str, Any]] = (await g.client.get(BASE)).json()["data"]["runContexts"]
    # The owner's context is listed first; the workflow's is the one this asks for.
    return next(c for c in contexts if c["id"] != "owner")


async def _test(g: Gateway, base: str, args: dict[str, Any], **extra: Any) -> dict[str, Any]:
    ctx = await _context(g)
    body = {"operation": g.tool(base), "contextId": ctx["id"], "target": "sandbox", "input": args, **extra}
    r = await g.client.post(f"{BASE}/test", json=body, headers=TEAM)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_sandbox_read_is_the_real_call(g: Gateway) -> None:
    out = await _test(g, "get_account", {"accountId": "CHQ-2219"})
    assert out["decision"] == "allow" and out["stubbed"] is False and out["reachedHost"]
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219"], "the system was called"
    assert out["output"]["accountId"] == "CHQ-2219" and out["output"]["holder"]["sin"] == "[redacted]", "masked"


async def test_a_real_write_in_a_workflows_context_needs_a_real_approval(g: Gateway) -> None:
    """simulateApproval stands in for an approval on Mock only: a real write never runs on a made-up one (ADR-0005)."""
    out = await _test(g, "place_hold", {"accountId": "CHQ-2219", "hours": 24}, simulateApproval=True)
    assert (out["decision"], out.get("denyReason")) == ("deny", "approval_token_missing"), out
    assert g.received == [], "nothing reached the system"


async def test_a_mock_write_sends_nothing(g: Gateway) -> None:
    args = {"accountId": "A", "hours": 24}
    body = {"operation": g.tool("place_hold"), "contextId": "owner", "target": "stub", "input": args}
    out = (await g.client.post(f"{BASE}/test", json=body)).json()["data"]
    assert out["decision"] == "allow" and g.received == [], out


async def test_a_sandbox_read_runs_the_published_call_not_a_staged_edit(g: Gateway) -> None:
    detail = (await g.client.get(BASE)).json()["data"]
    op_id = next(o["id"] for o in detail["operations"] if o["name"] == g.tool("get_account"))
    staged = await g.client.patch(f"{BASE}/operations/{op_id}", json={"path": "/limited"})
    assert staged.status_code == 200, staged.text
    await _test(g, "get_account", {"accountId": "CHQ-2219"})
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219"]


async def test_a_sandbox_read_that_fails_reports_the_side_and_status(g: Gateway) -> None:
    out = await _test(g, "limited", {})
    error = out["output"]["error"]
    assert (out["stubbed"], error["code"], error["side"], out["status"]) == (False, "RATE_LIMITED", "upstream", 429)


async def _as_owner(g: Gateway, base: str, args: dict[str, Any], environment: str = "test", **headers: str) -> Any:
    body = {
        "operation": g.tool(base), "contextId": "owner", "target": "sandbox", "input": args, "environment": environment
    }  # fmt: skip
    return await g.client.post(f"{BASE}/test", json=body, headers={**TEAM, **headers})


async def test_the_owner_reads_for_real_without_any_workflow_approval(g: Gateway) -> None:
    """No workflow holds an approval for the module; its owner still tries it (G9)."""
    r = await _as_owner(g, "get_account", {"accountId": "CHQ-2219"})
    assert r.status_code == 200, r.text
    out = r.json()["data"]
    assert (out["decision"], out["stubbed"]) == ("allow", False), (out.get("denyReason"), out.get("denyMessage"))
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219"], "the system was called"


async def test_a_real_write_runs_for_an_approver_and_is_logged_from_the_console(g: Gateway) -> None:
    """Real is a gateway call. The module holds place_hold for approval, and the dev caller, who passes every
    role rule, holds the approver role (reviews.decide), so a live run of it is not asked: the write runs, and the log
    names it as the write's approver under the console channel and a live run. A test run of the same write
    on this live account waits for a person instead (test_test_run_writes)."""
    r = await _as_owner(g, "place_hold", {"accountId": "CHQ-2219", "hours": 24}, "live")
    out = r.json()["data"]
    assert (out["decision"], out["stubbed"]) == ("allow", False), out
    assert [x["path"] for x in g.received] == ["/v1/holds"], "the system was called"
    rows = (await g.client.get("/v1/executions", params={"tool": g.tool("place_hold")})).json()["data"]["data"]
    assert [(x["channel"], x["environment"], x["decision"]) for x in rows] == [("console", "live", "allow")], rows
    assert rows[0]["approval"].get("by"), rows[0]["approval"]


async def test_a_team_that_does_not_own_the_module_cannot_try_it_as_owner(g: Gateway) -> None:
    r = await _as_owner(g, "get_account", {"accountId": "CHQ-2219"}, **{"X-Team-Id": "team_cards"})
    assert r.status_code == 404, "another team's module is not read at all: " + r.text
    assert g.received == []


async def test_the_panels_default_context_is_the_owner_even_with_a_workflow_waiting(g: Gateway) -> None:
    """A workflow asked for access but not yet approved lists a run context; the panel's default (the first) must still
    be the owner's, so the owner's try is not refused as that workflow's no_approval."""
    request = {
        "workflowId": "wf_dispute",
        "environment": "production",
        "operations": [g.tool("place_hold")],
        "expiresInDays": 30,
        "justification": "asked, not decided",
    }
    assert (await g.client.post(f"{BASE}/approvals", json=request)).status_code == 201
    first = (await g.client.get(BASE)).json()["data"]["runContexts"][0]
    body = {
        "operation": g.tool("place_hold"),
        "contextId": first["id"],
        "target": "sandbox",
        "input": {"accountId": "CHQ-2219", "hours": 24},
        "environment": "live",
    }
    out = (await g.client.post(f"{BASE}/test", json=body, headers=TEAM)).json()["data"]
    # Decided as the owner's try, never refused as the waiting workflow's no_approval.
    assert (first["id"], out["decision"]) == ("owner", "allow"), out


async def test_a_real_run_signs_in_with_the_sandbox_account_in_a_test_and_the_live_one_in_a_live_run(
    g: Gateway, engine: AsyncEngine
) -> None:
    """Real ran on whichever account the page did not pick; a test run now signs in with the app's sandbox
    account and a live run with its live account."""
    store = ModuleStore(engine)
    m = await store.get(g.tenant, MODULE)
    assert m is not None
    live = (await g.client.post("/v1/apps", json={"name": "Ledger", "authKind": "api_key"}, headers=TEAM)).json()[
        "data"
    ]
    sandbox = (
        await g.client.post(f"/v1/apps/{live['id']}/accounts", json={"name": "Sandbox", "sandbox": True}, headers=TEAM)
    ).json()["data"]
    for account, key in ((live, "k-prod"), (sandbox, "k-test")):
        fresh = (await g.client.get(f"/v1/apps/{live['id']}/accounts/{account['id']}", headers=TEAM)).json()["data"]
        body = {
            "revision": fresh["revision"],
            "settings": {"name": "X-Api-Key", "baseUrl": "https://bank.test/v1"},
            "secretValues": {"key": key},
        }
        put = await g.client.patch(f"/v1/apps/{live['id']}/accounts/{account['id']}", json=body, headers=TEAM)
        assert put.status_code == 200, put.text
    await store.put({**m, "connection_id": live["id"]}, expected_revision=m["revision"])
    body = {"operation": g.tool("get_account"), "contextId": "owner", "target": "sandbox", "input": {"accountId": "A"}}
    for env, key in (("live", "k-prod"), ("test", "k-test")):
        r = await g.client.post(f"{BASE}/test", json={**body, "environment": env}, headers=TEAM)
        assert r.json()["data"]["decision"] == "allow", r.text
        sent = g.received[-1]
        assert (sent["headers"].get("x-api-key"), sent["path"]) == (key, "/v1/accounts/A"), (env, sent)
