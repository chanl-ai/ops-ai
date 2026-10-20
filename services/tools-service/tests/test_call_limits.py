"""An operation's rate and amount limits on /v1/calls (c-028), one test per way a limit could fail to hold. The fake
bank records what reaches it, so "never sent" is checked on the upstream's side. Needs OPA (`make db-up`)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_service_kit.settings import Settings
from ops_tools.store.modules import ModuleStore
from ops_tools.store.rate_windows import RateWindows, operation_rate_windows

from .test_calls import MODULE, Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

ACCOUNT = {"accountId": "CHQ-2219"}


async def executions(g: Gateway, base: str) -> list[dict[str, Any]]:
    r = await g.client.get("/v1/executions", params={"tool": g.tool(base)})
    assert r.status_code == 200, r.text
    return r.json()["data"]["data"]


async def set_operation(engine: AsyncEngine, tenant: str, name: str, **values: Any) -> None:
    store = ModuleStore(engine)
    m = await store.get(tenant, MODULE)
    assert m is not None
    for o in m["operations"]:
        if o["name"] == name:
            o.update(values)
    await store.put(m, expected_revision=m["revision"])


async def clear_of_the_minute_edge(margin_s: float = 5) -> None:
    """The window is the database's calendar minute, so calls straddling one count in two windows and a limit test
    passes or fails by the clock. Waits out the last seconds of a minute first."""
    now = datetime.now(UTC)
    left = 60 - now.second - now.microsecond / 1e6
    if left < margin_s:
        await asyncio.sleep(left + 0.2)


async def test_the_call_after_the_limit_in_a_minute_is_refused_logged_and_never_sent(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    await clear_of_the_minute_edge()
    await set_operation(engine, tenant, gateway.tool("get_account"), rate_limit_per_min=2)
    codes = [(await gateway.call("get_account", ACCOUNT, step=f"s{i}")).status_code for i in range(2)]
    refused = await gateway.call("get_account", ACCOUNT, step="s2")
    assert codes == [200, 200]
    assert refused.status_code == 429, refused.text
    error = refused.json()["error"]
    assert error["code"] == "RATE_LIMITED" and error["details"]["limit"] == 2 and error["details"]["resetAt"]
    assert len(gateway.received) == 2, "the refused call never reached the upstream"
    rows = await executions(gateway, "get_account")
    assert sorted((r["step"], r["decision"]) for r in rows) == [("s0", "allow"), ("s1", "allow"), ("s2", "deny")]


async def test_the_count_lives_in_the_database_so_another_process_shares_it(tenant: str) -> None:
    await clear_of_the_minute_edge()
    url = Settings().database_url
    first, second = create_async_engine(url), create_async_engine(url)
    try:
        a, b = RateWindows(first), RateWindows(second)
        assert (await a.spend(tenant, "op_shared", 2)).allowed
        assert (await b.spend(tenant, "op_shared", 2)).allowed
        assert not (await a.spend(tenant, "op_shared", 2)).allowed, "the second process's call counted"
    finally:
        await first.dispose()
        await second.dispose()


async def test_calls_arriving_together_never_share_the_last_slot(engine: AsyncEngine, tenant: str) -> None:
    await clear_of_the_minute_edge()
    rates = RateWindows(engine)
    spent = await asyncio.gather(*(rates.spend(tenant, "op_burst", 3) for _ in range(8)))
    assert sum(s.allowed for s in spent) == 3


async def test_refused_calls_and_replays_spend_no_slot_and_a_limited_write_can_run_later(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    await clear_of_the_minute_edge()
    hold = gateway.tool("place_hold")
    await set_operation(engine, tenant, hold, rate_limit_per_min=1)
    args = {"accountId": "CHQ-2219", "hours": 24}
    assert (await gateway.call("place_hold", args, step="s1")).status_code == 403, "no token: refused by policy"
    assert (await gateway.call("place_hold", {**args, "hours": "x"}, step="s1")).status_code == 422
    ran = await gateway.call("place_hold", args, step="s1", token=gateway.token("place_hold", args, step="s1"))
    assert ran.status_code == 200, "the two refusals spent nothing, so the one slot was free"
    again = await gateway.call("place_hold", args, step="s1", token=gateway.token("place_hold", args, step="s1"))
    assert again.status_code == 200 and again.json()["data"].get("replayOf"), "a replay answers without a slot"
    limited = await gateway.call("place_hold", args, step="s2", token=gateway.token("place_hold", args, step="s2"))
    assert limited.status_code == 429, limited.text
    assert len([r for r in gateway.received if r["path"].endswith("/holds")]) == 1
    # The refusal gave its claim back: with room again, the same write runs instead of replaying the refusal.
    await set_operation(engine, tenant, hold, rate_limit_per_min=10)
    later = await gateway.call("place_hold", args, step="s2", token=gateway.token("place_hold", args, step="s2"))
    assert later.status_code == 200 and not later.json()["data"].get("replayOf"), later.text


async def test_an_amount_over_the_limit_or_missing_never_leaves_the_gateway(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    amount = {"name": "amount", "type": "number", "required": False}
    hold = gateway.tool("place_hold")
    fields = [
        {"name": "accountId", "type": "string", "required": True},
        {"name": "hours", "type": "integer", "required": True},
    ]
    await set_operation(engine, tenant, hold, amount_max=500, input=[*fields, amount])
    args = {"accountId": "CHQ-2219", "hours": 24}
    over = await gateway.call("place_hold", {**args, "amount": 500.01}, step="s1")
    assert over.status_code == 403 and over.json()["error"]["code"] == "amount_over_limit", over.text
    missing = await gateway.call("place_hold", args, step="s2")
    assert missing.status_code == 422 and missing.json()["error"]["code"] == "invalid_input", missing.text
    # A negative amount passes any upward cap; with an approval token it would otherwise reach the upstream.
    negative = {**args, "amount": -5_000_000}
    token = gateway.token("place_hold", negative, step="s3")
    flipped = await gateway.call("place_hold", negative, step="s3", token=token)
    assert flipped.status_code == 422 and flipped.json()["error"]["code"] == "invalid_input", flipped.text
    assert not gateway.received
    rows = await executions(gateway, "place_hold")
    assert sorted((r["step"], r["decision"]) for r in rows) == [("s1", "deny"), ("s2", "deny"), ("s3", "deny")]


async def test_the_test_panel_and_the_gateway_refuse_the_same_amount(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    amount = {"name": "amount", "type": "number", "required": False}
    hold = gateway.tool("place_hold")
    fields = [
        {"name": "accountId", "type": "string", "required": True},
        {"name": "hours", "type": "integer", "required": True},
    ]
    await set_operation(engine, tenant, hold, amount_max=500, input=[*fields, amount])
    args = {"accountId": "CHQ-2219", "hours": 24, "amount": 900}
    panel = await gateway.client.post(
        f"/v1/tool-modules/{MODULE}/test",
        json={"operation": hold, "contextId": "owner", "target": "stub", "input": args},
    )
    assert panel.status_code == 200, panel.text
    assert (panel.json()["data"]["decision"], panel.json()["data"]["denyReason"]) == ("deny", "constraint")
    call = await gateway.call("place_hold", args, step="s1")
    assert call.json()["error"]["code"] == "amount_over_limit"
    # A missing amount too: the panel's old copy of the check read it as 0 and allowed it.
    del args["amount"]
    panel = await gateway.client.post(
        f"/v1/tool-modules/{MODULE}/test",
        json={"operation": hold, "contextId": "owner", "target": "stub", "input": args},
    )
    assert panel.json()["data"]["decision"] == "deny"
    assert (await gateway.call("place_hold", args, step="s2")).json()["error"]["code"] == "invalid_input"


async def test_old_windows_are_pruned_when_an_operation_is_counted(engine: AsyncEngine, tenant: str) -> None:
    t = operation_rate_windows
    stale = datetime.now(UTC) - timedelta(hours=2)
    async with engine.begin() as c:
        await c.execute(t.insert().values(tenant_id=tenant, operation="op_old", window_start=stale, calls=9))
    await RateWindows(engine).spend(tenant, "op_old", 5)
    async with engine.connect() as c:
        starts = (await c.execute(sa.select(t.c.window_start).where(t.c.tenant_id == tenant))).scalars().all()
    assert all(s > stale for s in starts) and len(starts) == 1
