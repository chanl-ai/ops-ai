"""Trying one tool from a skill path or a workflow step (`POST /v1/tool-modules/tries`), by failure mode: a write
is sent without the person's confirm; a confirmed write on the app's test account is sent twice; a read does not run
for real."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from .test_calls import Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_test_run_writes import HOLD, _on_accounts, approver  # pyright: ignore[reportPrivateUsage]
from .test_write_approval_gateway import TeamAsksReviewer

TRY = "/v1/tool-modules/tries"


async def _team_saved_nothing(self: Any, tenant_id: str, team_id: str | None) -> tuple[Any, dict[str, Any]]:
    return {}, {}


@pytest.fixture(autouse=True)
def the_test_run_rule_asks_the_person(monkeypatch: pytest.MonkeyPatch) -> None:
    """The team saved no approval answer, so a test run's write asks the person who tried it, and their confirm is the
    whole approval."""
    monkeypatch.setattr(TeamAsksReviewer, "levels", _team_saved_nothing)


async def _try(g: Gateway, base: str, values: dict[str, Any], **extra: Any) -> dict[str, Any]:
    r = await g.client.post(TRY, json={"tool": g.tool(base), "input": values, **extra}, headers=approver(g))
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _calls(g: Gateway, base: str) -> list[dict[str, Any]]:
    r = await g.client.get("/v1/executions", params={"tool": g.tool(base)}, headers=approver(g))
    return r.json()["data"]["data"]


async def test_a_write_is_only_planned_until_the_person_confirms(gateway: Gateway) -> None:  # noqa: F811
    planned = await _try(gateway, "place_hold", HOLD)
    assert planned["kind"] == "planned", planned
    assert planned["plan"]["request"]["method"] == "POST", planned["plan"]
    assert planned["plan"]["request"]["url"].endswith("/holds"), planned["plan"]
    assert planned["plan"]["input"] == HOLD
    assert gateway.received == [], "the plan sent the write"
    assert await _calls(gateway, "place_hold") == [], "a plan was logged as a call"


async def test_a_confirmed_write_on_the_test_account_is_sent_once(gateway: Gateway, engine: AsyncEngine) -> None:  # noqa: F811
    await _on_accounts(gateway, engine, test_account=True)
    planned = await _try(gateway, "place_hold", HOLD)
    assert (planned["kind"], planned["live"]) == ("planned", False), planned
    changed = await gateway.client.post(
        TRY,
        json={"tool": gateway.tool("place_hold"), "input": {**HOLD, "hours": 48}, "planId": planned["planId"]},
        headers=approver(gateway),
    )
    assert changed.status_code == 409, "values edited after the plan were sent under its confirm"
    sent = await _try(gateway, "place_hold", HOLD, planId=planned["planId"])
    assert (sent["kind"], sent["ok"]) == ("sent", True), sent
    again = await _try(gateway, "place_hold", HOLD, planId=planned["planId"])
    assert again.get("replayOf") == sent["callId"], again
    assert len([r for r in gateway.received if r["path"] == "/v1/holds"]) == 1, gateway.received


async def test_a_read_runs_for_real(gateway: Gateway) -> None:  # noqa: F811
    ran = await _try(gateway, "get_account", {"accountId": "A"})
    assert (ran["kind"], ran["ok"]) == ("ran", True), ran
    assert [x["path"] for x in gateway.received] == ["/v1/accounts/A"]
