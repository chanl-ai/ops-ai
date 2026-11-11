"""An approval the person who asked gave themselves, checked again when the write is sent, by failure mode: the
asker approved while requesterMayDecide let them (or while the write needed no reviewer), the policy changed before the
call, and the gateway still ran the write on that token. The gateway reads today's policy at the call, so the token
counts only while the asker may still decide. Rig: test_calls' gateway and fake bank; the person is acting-for."""

from __future__ import annotations

from typing import Any

import pytest

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint as mint_claims
from ops_service_kit.ids import input_hash
from ops_tools.tokens import Binding, mint

from .conftest import REVIEW_KEY
from .test_calls import Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

ASKER = "j.richardson@bank.test"
ARGS = {"accountId": "CHQ-2219", "hours": 24}


def acting_for_asker(tenant: str) -> dict[str, str]:
    """agents-service's token for a chat turn in the module's team, acting for the person who asked."""
    service = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, team_id="team_platform"
    )
    claims = {
        "sub": "usr_james",
        "email": ASKER,
        "name": "James Richardson",
        "tenant_id": tenant,
        "team_id": "team_platform",
        "kind": "acting_for",
        "act": {"sub": "service:agents"},
        "aud": "tools",
    }
    return {
        "Authorization": f"Bearer {service}",
        "X-Acting-For": mint_claims(claims, dev_service_signer(), ttl_s=TEST_TOKEN_TTL_S),
    }


async def send(g: Gateway, approver: str) -> Any:
    tool = g.tool("place_hold")
    token = mint(Binding(g.thread, "s1", tool, input_hash(ARGS), [approver]), REVIEW_KEY, ttl_s=300)
    body = {
        "tool": tool,
        "input": ARGS,
        "key": "s1",
        "runContext": {"thread": g.thread, "step": "s1", "act": "agent:dispute_triage"},
        "approvalToken": token,
    }
    return await g.client.post("/v1/calls", json=body, headers=acting_for_asker(g.tenant))


async def test_the_askers_own_approval_is_refused_once_the_policy_no_longer_lets_them_decide(gateway: Gateway) -> None:
    # The token was minted while the asker could decide; at the call requesterMayDecide is off (the default).
    refused = await send(gateway, ASKER)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "own_request", refused.text
    assert not gateway.received, "the write never reached the system"


async def test_another_persons_approval_still_runs_the_write(gateway: Gateway) -> None:
    ran = await send(gateway, "m.okafor@bank.test")
    assert ran.status_code == 200, ran.text


@pytest.mark.usefixtures("requester_may_decide_on")
async def test_the_askers_own_approval_runs_while_the_policy_lets_them_decide(gateway: Gateway) -> None:
    ran = await send(gateway, ASKER)
    assert ran.status_code == 200, ran.text


@pytest.fixture
def requester_may_decide_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPS_DEV_POLICIES", '{"requesterMayDecide": true}')
