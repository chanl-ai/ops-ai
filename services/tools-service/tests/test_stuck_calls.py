"""A stuck call never hangs a run (c-558), by failure mode: a hand-built body template quotes a placeholder, which is
filled in as JSON and so can never make a request, and the executor fails on a call in a way it does not answer for,
which left a write's row running so the engine could neither retry the step nor end it. Needs OPA (`make db-up`)."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine

from .test_call_limits import executions, set_operation
from .test_calls import MODULE, Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

HOLD = {"accountId": "CHQ-2219", "hours": 24}


async def test_a_body_template_that_quotes_a_placeholder_is_refused_at_save(gateway: Gateway) -> None:
    page = f"/v1/tool-modules/{MODULE}"
    ops = (await gateway.client.get(page)).json()["data"]["operations"]
    op = next(o for o in ops if o["name"] == gateway.tool("place_hold"))
    quoted = '{"account": "{{accountId}}", "hours": {{hours}}}'
    r = await gateway.client.patch(f"{page}/operations/{op['id']}", json={"body": quoted})
    assert r.status_code == 400, r.text
    assert "{{accountId}}" in r.json()["error"]["message"], r.text
    unquoted = '{"account": {{accountId}}, "hours": {{hours}}}'
    ok = await gateway.client.patch(f"{page}/operations/{op['id']}", json={"body": unquoted})
    assert ok.status_code == 200, ok.text


async def test_a_write_the_executor_fails_on_is_closed_as_failed(
    gateway: Gateway, engine: AsyncEngine, tenant: str
) -> None:
    # Saved before the check above existed: the quoted placeholder fills to `""CHQ-2219""`, which is not JSON.
    await set_operation(engine, tenant, gateway.tool("place_hold"), body='{"account": "{{accountId}}"}')
    token = gateway.token("place_hold", HOLD, step="s1")
    r = await gateway.call("place_hold", HOLD, step="s1", token=token)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["ok"] is False and data["output"]["error"]["code"] == "CALL_FAILED", data
    row = next(x for x in await executions(gateway, "place_hold") if x["id"] == data["callId"])
    assert row["status"] == "error", row
    # The same key again answers with that failure rather than "the same write is already running".
    again = await gateway.call("place_hold", HOLD, step="s1", token=token)
    assert again.status_code == 200 and again.json()["data"]["ok"] is False, again.text
