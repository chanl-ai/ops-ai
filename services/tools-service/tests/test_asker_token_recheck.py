"""An approval the person who asked gave themselves, checked again when the write is sent, by failure mode: the
asker approved while they held Approvals decide (or while the write needed no reviewer), the cell was unticked before
the call, and the gateway still ran the write on that token. The gateway asks platform-service's access check at the
call, so the token counts only while the asker holds the cell now, whatever roles their acting-for token claims. Rig:
test_calls' gateway and fake bank with a fake access check; the person is acting-for."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import dev_service_signer, mint_service_token
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint as mint_claims
from ops_service_kit.ids import input_hash
from ops_tools.modules.policy import OwnRequests
from ops_tools.tokens import Binding, mint

from .conftest import REVIEW_KEY
from .test_apply_tool_access import Platform
from .test_calls import Gateway, gateway, serve_gateway
from .test_write_approval_gateway import TeamAsksReviewer

__all__ = ["gateway"]  # the fixture, used by name

ASKER = "j.richardson@bank.test"
ARGS = {"accountId": "CHQ-2219", "hours": 24}


def acting_for_asker(tenant: str, **held: Any) -> dict[str, str]:
    """agents-service's token for a chat turn in the module's team, acting for the person who asked; `held` adds the
    access claims a session's token carries (their roles)."""
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
        **held,
    }
    return {
        "Authorization": f"Bearer {service}",
        "X-Acting-For": mint_claims(claims, dev_service_signer(), ttl_s=TEST_TOKEN_TTL_S),
    }


async def send(g: Gateway, approver: str, **held: Any) -> Any:
    tool = g.tool("place_hold")
    token = mint(Binding(g.thread, "s1", tool, input_hash(ARGS), [approver]), REVIEW_KEY, ttl_s=300)
    body = {
        "tool": tool,
        "input": ARGS,
        "key": "s1",
        "runContext": {"thread": g.thread, "step": "s1", "act": "agent:dispute_triage"},
        "approvalToken": token,
    }
    return await g.client.post("/v1/calls", json=body, headers=acting_for_asker(g.tenant, **held))


@pytest.fixture
def holders() -> set[str]:
    """Who holds Approvals decide in the module's team, as platform-service's access check answers now."""
    return set()


@pytest.fixture
async def checked(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], holders: set[str]
) -> AsyncIterator[Gateway]:
    own = OwnRequests(cast(Any, Platform(holders)))
    async with serve_gateway(engine, seed, tenant, catalog_tools, own_requests=own) as g:
        yield g


async def test_the_askers_own_approval_is_refused_once_they_no_longer_hold_the_cell(checked: Gateway) -> None:
    # The token was minted while the asker could decide; at the call they no longer hold Approvals decide.
    refused = await send(checked, ASKER)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "own_request", refused.text
    assert not checked.received, "the write never reached the system"


async def test_another_persons_approval_still_runs_the_write(checked: Gateway) -> None:
    ran = await send(checked, "m.okafor@bank.test")
    assert ran.status_code == 200, ran.text


async def test_the_askers_own_approval_runs_while_they_hold_the_cell(checked: Gateway, holders: set[str]) -> None:
    holders.add(ASKER)
    ran = await send(checked, ASKER)
    assert ran.status_code == 200, ran.text


async def test_an_acting_for_token_claiming_admin_does_not_decide_without_the_cell(checked: Gateway) -> None:
    refused = await send(checked, ASKER, access={"team_platform": ["admin"]})
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "own_request", refused.text


@pytest.fixture
def team_asks_the_person(monkeypatch: pytest.MonkeyPatch) -> None:
    async def levels(self: Any, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        return {"ask": True, "answer": "person", "reviewerRole": None}, {}

    monkeypatch.setattr(TeamAsksReviewer, "levels", levels)


@pytest.mark.usefixtures("team_asks_the_person")
async def test_when_the_team_asks_the_person_their_allow_runs_the_write(gateway: Gateway) -> None:
    # "Ask the person" is the asker's own confirmation; the own-request rule belongs to reviewer mode only.
    ran = await send(gateway, ASKER)
    assert ran.status_code == 200, ran.text
    logged = await gateway.client.get("/v1/executions", params={"tool": gateway.tool("place_hold")})
    [row] = logged.json()["data"]["data"]
    assert row["status"] == "ok", row
