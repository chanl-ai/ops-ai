"""The call log names a replay and a same-write-running refusal for what they are (c-041), so the executions table
agrees row for row with the module's call and denied counts. Needs OPA (`make db-up`)."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.calls import gateway_calls

from .test_call_limits import executions
from .test_calls import MODULE, Gateway, gateway

__all__ = ["gateway"]  # the fixture, used by name

HOLD = {"accountId": "CHQ-2219", "hours": 24}


async def counts(g: Gateway, base: str) -> tuple[int, int]:
    """(the operation's calls · 24h, the module's denied · 24h)."""
    page = (await g.client.get(f"/v1/tool-modules/{MODULE}")).json()["data"]
    activity = (await g.client.get(f"/v1/tool-modules/{MODULE}/activity")).json()["data"]
    calls = next(o["calls24h"] for o in page["operations"] if o["name"] == g.tool(base))
    return calls, activity["denied24h"]


async def test_a_replayed_write_is_listed_as_a_replay_of_the_call_it_repeated(gateway: Gateway) -> None:
    before = await counts(gateway, "place_hold")
    token = gateway.token("place_hold", HOLD, step="s1")
    first = await gateway.call("place_hold", HOLD, step="s1", token=token)
    again = await gateway.call("place_hold", HOLD, step="s1", token=token)
    assert first.status_code == again.status_code == 200, again.text
    rows = {r["id"]: r for r in await executions(gateway, "place_hold")}
    ran = rows[first.json()["data"]["callId"]]
    replay = rows[again.json()["data"]["callId"]]
    assert ran["status"] == "ok" and "replayOf" not in ran
    assert replay["status"] == "replayed" and replay["replayOf"] == ran["id"]
    after = await counts(gateway, "place_hold")
    assert (after[0] - before[0], after[1] - before[1]) == (1, 0), "the replay ran nothing, so it is not a call"


async def test_a_write_refused_while_the_same_one_runs_is_a_denial_with_its_reason(
    gateway: Gateway, engine: AsyncEngine
) -> None:
    denied = (await counts(gateway, "place_hold"))[1]
    token = gateway.token("place_hold", HOLD, step="s1")
    first = await gateway.call("place_hold", HOLD, step="s1", token=token)
    # The first write still running is what makes the gateway refuse the second.
    async with engine.begin() as c:
        await c.execute(
            sa.update(gateway_calls)
            .where(gateway_calls.c.id == first.json()["data"]["callId"])
            .values(outcome="running")
        )
    refused = await gateway.call("place_hold", HOLD, step="s1", token=token)
    assert refused.status_code == 409, refused.text
    row: dict[str, Any] = next(
        r for r in await executions(gateway, "place_hold") if r["id"] != first.json()["data"]["callId"]
    )
    assert (row["status"], row["decision"]) == ("denied", "deny")
    assert "already running" in row["denyReason"]
    assert (await counts(gateway, "place_hold"))[1] == denied + 1, "the refusal counts under denied"
