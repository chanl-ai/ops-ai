"""A write in a test run, by failure mode: a person who may approve writes runs a tool page's Real test of a write on
the app's live account and it reaches the system, with nobody asked (their role approved it for them); the same
write on the app's test account is held back; and a live run's write stops following the team's approval policy."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .test_calls import MODULE, Gateway, gateway  # noqa: F401  # pyright: ignore[reportUnusedImport]

BASE = f"/v1/tool-modules/{MODULE}"
TEAM = "team_platform"
HOLD = {"accountId": "CHQ-2219", "hours": 24}


@pytest.fixture
async def g(gateway: Gateway) -> Gateway:  # noqa: F811
    return gateway


def approver(g: Gateway) -> dict[str, str]:
    """The seed's own person acting in the team that owns the bank module, as the console sends a request; in dev mode
    they hold every role, the approver's among them, so they approve their own writes when approval is asked."""
    return {"X-Team-Id": TEAM}


async def _on_accounts(g: Gateway, engine: AsyncEngine, *, test_account: bool) -> None:
    """The bank module on an app's live account, and with `test_account` a test account beside it."""
    who = approver(g)
    live = (await g.client.post("/v1/apps", json={"name": "Ledger", "authKind": "api_key"}, headers=who)).json()["data"]
    accounts = [live]
    if test_account:
        body = {"name": "Testing", "sandbox": True}
        accounts.append((await g.client.post(f"/v1/apps/{live['id']}/accounts", json=body, headers=who)).json()["data"])
    for account in accounts:
        fresh = (await g.client.get(f"/v1/apps/{live['id']}/accounts/{account['id']}", headers=who)).json()["data"]
        keys = {
            "revision": fresh["revision"],
            "settings": {"name": "X-Api-Key", "baseUrl": "https://bank.test/v1"},
            "secretValues": {"key": "k-" + account["id"]},
        }
        saved = await g.client.patch(f"/v1/apps/{live['id']}/accounts/{account['id']}", json=keys, headers=who)
        assert saved.status_code == 200, saved.text
    store = ModuleStore(engine)
    m = await store.get(g.tenant, MODULE)
    assert m is not None
    await store.put({**m, "connection_id": live["id"]}, expected_revision=m["revision"])


async def _real(g: Gateway, environment: str) -> dict[str, Any]:
    body = {
        "operation": g.tool("place_hold"),
        "contextId": "owner",
        "target": "sandbox",
        "input": HOLD,
        "environment": environment,
    }
    r = await g.client.post(f"{BASE}/test", json=body, headers=approver(g))
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_a_test_runs_write_on_a_live_account_never_reaches_the_system(g: Gateway, engine: AsyncEngine) -> None:
    await _on_accounts(g, engine, test_account=False)
    out = await _real(g, "test")
    assert out["decision"] == "deny", out
    assert "approval" in out["denyMessage"], out
    assert not [r for r in g.received if r["path"] == "/v1/holds"], g.received


async def test_a_test_runs_write_on_a_test_account_is_sent(g: Gateway, engine: AsyncEngine) -> None:
    await _on_accounts(g, engine, test_account=True)
    out = await _real(g, "test")
    assert out["decision"] == "allow", out
    sent = [r for r in g.received if r["path"] == "/v1/holds"]
    assert len(sent) == 1 and sent[0]["headers"].get("x-api-key", "").startswith("k-ca_"), sent


async def test_a_live_runs_write_follows_the_teams_approval_policy(g: Gateway, engine: AsyncEngine) -> None:
    # The bank's place_hold asks for approval; a person who holds the approver role approves their own live write,
    # as every live call by them does.
    await _on_accounts(g, engine, test_account=False)
    out = await _real(g, "production")
    assert out["decision"] == "allow", out
    assert len([r for r in g.received if r["path"] == "/v1/holds"]) == 1, g.received
