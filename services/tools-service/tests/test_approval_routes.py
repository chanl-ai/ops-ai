"""The gateway decides a call before it is made and is the one minter of approval tokens, by failure mode: a decision
sends the write or logs it, a minted token runs a write twice, the person who asked approves their own write while the
two-person rule is on, and a step that already sent its write gets a token for another one. Rig: test_calls' gateway
and fake bank, where the team asks a reviewer before a write."""

from __future__ import annotations

from typing import Any

import pytest

from ops_service_kit.ids import input_hash

from .conftest import service_headers
from .test_asker_token_recheck import ASKER, acting_for_asker
from .test_calls import Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

ARGS = {"accountId": "CHQ-2219", "hours": 24}
REVIEWER = "m.okafor@bank.test"


def call_body(g: Gateway, args: dict[str, Any], step: str, token: str | None = None) -> dict[str, Any]:
    return {
        "tool": g.tool("place_hold"),
        "input": args,
        "key": step,
        "runContext": {"thread": g.thread, "step": step, "act": "agent:dispute_triage"},
        "approvalToken": token,
    }


async def approve(g: Gateway, args: dict[str, Any], step: str, approvers: list[str]) -> Any:
    body = {
        "binding": {"threadId": g.thread, "step": step, "tool": g.tool("place_hold"), "inputHash": input_hash(args)},
        "input": args,
        "approvers": approvers,
    }
    return await g.client.post("/v1/approvals", json=body, headers=acting_for_asker(g.tenant))


async def test_decide_says_a_write_waits_for_a_person_and_sends_nothing(gateway: Gateway) -> None:
    r = await gateway.client.post(
        "/v1/calls/decide", json=call_body(gateway, ARGS, "s1"), headers=service_headers(gateway.tenant)
    )
    assert r.status_code == 200, r.text
    got = r.json()["data"]
    assert (got["verdict"], got["inputHash"], got["approversNeeded"]) == ("needs_review", input_hash(ARGS), 1), got
    assert not gateway.received, "a decision never reaches the system"
    logged = await gateway.client.get("/v1/executions", params={"tool": gateway.tool("place_hold")})
    assert logged.json()["data"]["data"] == [], "a decision writes no call row"


async def test_a_minted_token_lets_the_write_through_once(gateway: Gateway) -> None:
    minted = await approve(gateway, ARGS, "s1", [REVIEWER])
    assert minted.status_code == 200, minted.text
    token = minted.json()["data"]["token"]
    headers = acting_for_asker(gateway.tenant)
    first = await gateway.client.post("/v1/calls", json=call_body(gateway, ARGS, "s1", token), headers=headers)
    again = await gateway.client.post("/v1/calls", json=call_body(gateway, ARGS, "s1", token), headers=headers)
    assert (first.status_code, again.status_code) == (200, 200), (first.text, again.text)
    assert again.json()["data"]["replayOf"] == first.json()["data"]["callId"]
    assert len(gateway.received) == 1, "the system received the write once"


@pytest.mark.usefixtures("two_person_rule_on")
async def test_the_askers_own_approval_is_refused_under_the_two_person_rule(gateway: Gateway) -> None:
    refused = await approve(gateway, ARGS, "s1", [ASKER])
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "requester_cannot_approve", refused.text


async def test_a_step_that_already_sent_its_write_is_closed_to_another_approval(gateway: Gateway) -> None:
    token = (await approve(gateway, ARGS, "s1", [REVIEWER])).json()["data"]["token"]
    ran = await gateway.client.post(
        "/v1/calls", json=call_body(gateway, ARGS, "s1", token), headers=acting_for_asker(gateway.tenant)
    )
    assert ran.status_code == 200, ran.text
    closed = await approve(gateway, {**ARGS, "hours": 48}, "s1", [REVIEWER])
    assert closed.status_code == 409, closed.text
    assert closed.json()["error"]["code"] == "interrupt_closed", closed.text


@pytest.fixture
def two_person_rule_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DEV_POLICIES", '{"requesterMayDecide": false}')
