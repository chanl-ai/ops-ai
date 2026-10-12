"""One test per way a write could get through the gateway without the approval it needs."""

from __future__ import annotations

import time
from typing import Any

from .conftest import Gateway

HOLD = {"wireId": "W-88213", "hours": 24, "reason": "First wire to a payee added this morning."}
DOC = {"customerId": "C-1042", "document": "proof of address", "reason": "Address changed last week."}


def reasons(r: Any) -> list[str]:
    return r.json()["error"]["details"]["reasons"]


async def test_read_needs_no_token(gateway: Gateway) -> None:
    r = await gateway.call("lookup_account", {"query": "CHQ-2219"}, step="s1")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["decision"] == "allow"


async def test_unregistered_identity_is_refused(gateway: Gateway) -> None:
    r = await gateway.call("lookup_account", {"query": "CHQ-2219"}, step="s1", service="someone")
    assert r.status_code == 403
    assert reasons(r) == ["caller identity is not registered"]


async def test_unknown_tool_is_refused(gateway: Gateway) -> None:
    r = await gateway.call("drop_tables", {}, step="s1")
    assert r.status_code == 403
    assert "tool is not registered with the gateway" in reasons(r)


async def test_write_without_token_is_refused(gateway: Gateway) -> None:
    r = await gateway.call("request_document", DOC, step="s2")
    assert r.status_code == 403
    assert reasons(r) == ["write needs an approval token"]


async def test_write_with_token_runs(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s2", approvers=["dana@bank.test"])
    r = await gateway.call("request_document", DOC, step="s2", token=token)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["output"]["status"] == "completed"


async def test_input_edited_after_approval_is_refused(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s3", approvers=["dana@bank.test"])
    r = await gateway.call("request_document", {**DOC, "document": "bank statements"}, step="s3", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token was issued for a different input"]


async def test_reordered_keys_are_the_same_input(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s4", approvers=["dana@bank.test"])
    r = await gateway.call("request_document", dict(reversed(DOC.items())), step="s4", token=token)
    assert r.status_code == 200, r.text


async def test_number_written_as_float_is_the_same_input(gateway: Gateway) -> None:
    # RFC 8785 writes 24 and 24.0 the same, so an approval of 24 hours is not refused when the call carries 24.0.
    # A different number is still a different input.
    token = gateway.token("place_wire_hold", HOLD, step="s5", approvers=["dana@bank.test", "lee@bank.test"])
    other = await gateway.call("place_wire_hold", {**HOLD, "hours": 25}, step="s5", token=token)
    assert other.status_code == 403
    assert reasons(other) == ["approval token was issued for a different input"]
    same = await gateway.call("place_wire_hold", {**HOLD, "hours": 24.0}, step="s5", token=token)
    assert same.status_code == 200, same.text


async def test_expired_token_is_refused(gateway: Gateway) -> None:
    gateway.clock.at = 1_800_000_000.0
    token = gateway.token(
        "request_document", DOC, step="s6", approvers=["dana@bank.test"], ttl_s=60, now=1_800_000_000.0 - 120
    )
    r = await gateway.call("request_document", DOC, step="s6", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token has expired"]


async def test_expiry_is_judged_by_the_gateways_clock_not_opas(gateway: Gateway) -> None:
    # OPA's clock (a container's) can lag the host; judged by it, a token past expiry by the gateway's time passed.
    token = gateway.token("request_document", DOC, step="s6b", approvers=["dana@bank.test"], ttl_s=60)
    gateway.clock.at = time.time() + 3600
    r = await gateway.call("request_document", DOC, step="s6b", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token has expired"]


async def test_token_from_another_thread_is_refused(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s7", approvers=["dana@bank.test"], thread="gth_other")
    r = await gateway.call("request_document", DOC, step="s7", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token belongs to another thread"]


async def test_token_for_another_step_is_refused(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s8", approvers=["dana@bank.test"])
    r = await gateway.call("request_document", DOC, step="s9", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token is for another step"]


async def test_token_signed_with_another_key_is_refused(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s10", approvers=["dana@bank.test"], key="not-the-key")
    r = await gateway.call("request_document", DOC, step="s10", token=token)
    assert r.status_code == 403
    assert reasons(r) == ["approval token is not signed by the review service"]


async def test_money_write_needs_two_approvers(gateway: Gateway) -> None:
    one = gateway.token("place_wire_hold", HOLD, step="s11", approvers=["dana@bank.test"])
    r = await gateway.call("place_wire_hold", HOLD, step="s11", token=one)
    assert r.status_code == 403
    assert reasons(r) == ["moving money needs two approvers; the token has 1"]

    same_twice = gateway.token("place_wire_hold", HOLD, step="s11", approvers=["dana@bank.test", "dana@bank.test"])
    r = await gateway.call("place_wire_hold", HOLD, step="s11", token=same_twice)
    assert reasons(r) == ["moving money needs two approvers; the token has 1"]

    two = gateway.token("place_wire_hold", HOLD, step="s11", approvers=["dana@bank.test", "lee@bank.test"])
    r = await gateway.call("place_wire_hold", HOLD, step="s11", token=two)
    assert r.status_code == 200, r.text


async def test_every_call_is_logged_with_its_decision(gateway: Gateway) -> None:
    await gateway.call("request_document", DOC, step="s12")
    token = gateway.token("request_document", DOC, step="s12", approvers=["dana@bank.test"])
    await gateway.call("request_document", DOC, step="s12", token=token)
    rows = await gateway.log.for_thread(gateway.thread)
    assert [(r["decision"], r["outcome"], r["reasons"]) for r in rows] == [
        ("deny", "refused", ["write needs an approval token"]),
        ("allow", "ok", []),
    ]
    assert rows[1]["approvers"] == ["dana@bank.test"]


async def test_same_approved_write_twice_runs_once(gateway: Gateway) -> None:
    token = gateway.token("request_document", DOC, step="s13", approvers=["dana@bank.test"])
    first = (await gateway.call("request_document", DOC, step="s13", token=token)).json()["data"]
    again = (await gateway.call("request_document", DOC, step="s13", token=token)).json()["data"]
    assert again["output"] == first["output"]
    assert again["replayOf"] == first["callId"]
    rows = await gateway.log.for_thread(gateway.thread)
    assert [(r["outcome"], r["effect"]) for r in rows] == [("ok", True), ("replayed", False)]


async def test_a_call_without_a_service_token_is_refused_before_policy(gateway: Gateway) -> None:
    """The caller is the verified service token's subject; with no token there is no caller to decide for."""
    body = {"tool": "lookup_account", "input": {"query": "CHQ-2219"}, "key": "s1", "runContext": {"step": "s1"}}
    r = await gateway.client.post("/v1/calls", json=body, headers={"Authorization": ""})
    assert r.status_code == 401, r.text
