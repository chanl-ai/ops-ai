"""The test console's "Test environment" target (c-038): a read is the real call the gateway would make, a write
answers from the stub and says so. One test per way the panel could claim a call it did not make."""

from __future__ import annotations

from typing import Any

import pytest

from .test_apply_tool_access import apply_access
from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

BASE = f"/v1/tool-modules/{MODULE}"


@pytest.fixture
async def g(gateway: Gateway) -> Gateway:  # noqa: F811
    return gateway


SECURITY = {"X-Dev-User": "Nadia Petrov"}


async def _context(g: Gateway) -> dict[str, Any]:
    """A run context to test as: a workflow approved for the bank module's operations, decided by a second person."""
    request = {
        "workflowId": "wf_dispute",
        "environment": "production",
        "operations": [g.tool("get_account"), g.tool("place_hold"), g.tool("limited")],
        "expiresInDays": 30,
        "justification": "c-038 test console",
    }
    approval = await g.client.post(f"{BASE}/approvals", json=request)
    assert approval.status_code == 201, approval.text
    decided = await apply_access(g.client, g.tenant, {**approval.json()["data"], "moduleId": MODULE})
    assert decided.status_code == 200 and decided.json()["data"]["ok"], decided.text
    contexts: list[dict[str, Any]] = (await g.client.get(BASE)).json()["data"]["runContexts"]
    assert contexts, "the approved workflow has a case to test as"
    return contexts[0]


async def _test(g: Gateway, base: str, args: dict[str, Any], **extra: Any) -> dict[str, Any]:
    ctx = await _context(g)
    body = {"operation": g.tool(base), "contextId": ctx["id"], "target": "sandbox", "input": args, **extra}
    r = await g.client.post(f"{BASE}/test", json=body)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_sandbox_read_is_the_real_call(g: Gateway) -> None:
    out = await _test(g, "get_account", {"accountId": "CHQ-2219"})
    assert out["decision"] == "allow" and out["stubbed"] is False and out["reachedHost"]
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219"], "the system was called"
    assert out["output"]["accountId"] == "CHQ-2219" and out["output"]["holder"]["sin"] == "[redacted]", "masked"


async def test_a_sandbox_write_answers_from_the_stub_and_says_so(g: Gateway) -> None:
    out = await _test(g, "place_hold", {"accountId": "CHQ-2219", "hours": 24}, simulateApproval=True)
    assert out["decision"] == "allow" and out["stubbed"] is True
    assert g.received == [], "a test console never writes to the system"


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


async def _as_owner(g: Gateway, base: str, args: dict[str, Any], **headers: str) -> Any:
    body = {"operation": g.tool(base), "contextId": "owner", "target": "sandbox", "input": args}
    return await g.client.post(f"{BASE}/test", json=body, headers=headers)


async def test_the_owner_reads_for_real_without_any_workflow_approval(g: Gateway) -> None:
    """No workflow holds an approval for the module; its owner still tries it (c-048 T008, G9)."""
    r = await _as_owner(g, "get_account", {"accountId": "CHQ-2219"})
    assert r.status_code == 200, r.text
    out = r.json()["data"]
    assert (out["decision"], out["stubbed"]) == ("allow", False), out
    assert [x["path"] for x in g.received] == ["/v1/accounts/CHQ-2219"], "the system was called"


async def test_the_owners_write_answers_from_the_stub_and_never_reaches_the_system(g: Gateway) -> None:
    r = await _as_owner(g, "place_hold", {"accountId": "CHQ-2219", "hours": 24})
    out = r.json()["data"]
    assert (out["decision"], out["stubbed"]) == ("allow", True), out
    assert g.received == [], "a test console never writes to the system"


async def test_a_team_that_does_not_own_the_module_cannot_try_it_as_owner(g: Gateway) -> None:
    r = await _as_owner(g, "get_account", {"accountId": "CHQ-2219"}, **{"X-Team-Id": "team_cards"})
    assert r.status_code == 404, "another team's module is not read at all (c-423): " + r.text
    assert g.received == []


async def test_the_panels_default_context_is_the_owner_even_with_a_workflow_waiting(g: Gateway) -> None:
    """A workflow asked for access but not yet approved lists a run context; the panel's default (the first) must still
    be the owner's, so the owner's try is not refused as that workflow's no_approval (c-048 T019)."""
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
    }
    out = (await g.client.post(f"{BASE}/test", json=body)).json()["data"]
    assert (first["id"], out["decision"], out["stubbed"]) == ("owner", "allow", True), out
