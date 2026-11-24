"""A Real test run of a write on an app's live account asks the person who pressed Run first (the console's approval
card). Their yes is a flag on the run; without it, or for any answer but "ask the person", nothing is sent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.modules.policy import OwnRequests

from .test_apply_tool_access import Platform
from .test_calls import Gateway, serve_gateway
from .test_test_run_writes import BASE, HOLD, _on_accounts, approver  # pyright: ignore[reportPrivateUsage]
from .test_write_approval_gateway import TeamAsksReviewer


async def _team_saved_nothing(self: Any, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
    return {}, {}


@pytest.fixture(autouse=True)
def nobody_approves_their_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """The team has saved nothing, so the test-run rule alone asks the person."""
    monkeypatch.setattr(TeamAsksReviewer, "levels", _team_saved_nothing)


@pytest.fixture
async def g(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Gateway]:
    """The person who pressed Run does not hold Approvals decide, as platform-service's access check answers, so only
    their yes can let the write run."""
    own = OwnRequests(cast(Any, Platform(set())))
    async with serve_gateway(engine, seed, tenant, catalog_tools, own_requests=own) as gw:
        yield gw


async def _run(g: Gateway, **extra: Any) -> dict[str, Any]:
    body = {"operation": g.tool("place_hold"), "contextId": "owner", "target": "sandbox", "input": HOLD, **extra}
    r = await g.client.post(f"{BASE}/test", json=body, headers=approver(g))
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_live_account_test_run_waits_for_the_persons_yes_then_runs(g: Gateway, engine: AsyncEngine) -> None:
    await _on_accounts(g, engine, test_account=False)
    asked = await _run(g)
    assert (asked["decision"], asked.get("denyReason")) == ("deny", "approval_token_missing"), asked
    assert g.received == [], "nothing was sent before the yes"
    said_yes = await _run(g, confirmed=True)
    assert said_yes["decision"] == "allow", (said_yes.get("denyReason"), said_yes.get("denyMessage"))
    assert len([r for r in g.received if r["path"] == "/v1/holds"]) == 1, g.received


async def test_a_reviewer_answer_is_not_let_through_by_the_persons_yes(
    g: Gateway, engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def reviewer(self: Any, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
        return {"ask": True, "answer": "reviewer", "reviewerRole": None}, {}

    monkeypatch.setattr(TeamAsksReviewer, "levels", reviewer)
    await _on_accounts(g, engine, test_account=False)
    held = await _run(g, confirmed=True)
    assert (held["decision"], held.get("denyReason")) == ("deny", "approval_token_missing"), held
    assert g.received == [], "the asker's yes sent a write the team gave to a reviewer"
