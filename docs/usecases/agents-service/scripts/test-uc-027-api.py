"""uc-027 an approval outlives its token, api layer: docs/usecases/agents-service/approval-outlives-its-token.md."""

from __future__ import annotations

import asyncio
import os
import time

# Tokens expire one second after a decision, so a resume that waits on a busy thread meets an expired token.
os.environ["OPS_REVIEW_TOKEN_TTL_SECONDS"] = "1"

from sqlalchemy.ext.asyncio import create_async_engine
from usecase_harness import DB, EMAILS, TEAM, agents, check, data, finish, new_thread, run, tools

from ops_agents.store.leases import Leases

PG = os.environ.get("OPS_PG_PORT", "5477")


def hold(tid: str, release: bool = False) -> None:
    """Precondition: another run holds the thread, as a long run or a stalled worker would."""

    async def go() -> None:
        engine = create_async_engine(f"postgresql+asyncpg://ops:ops@localhost:{PG}/{DB}")
        leases = Leases(engine, owner="uc-027-other-run", ttl=60)
        await (leases.release(tid, "run_other") if release else leases.acquire(tid, "run_other"))
        await engine.dispose()

    asyncio.run(go())


with tools() as gateway, agents(gateway_url=str(gateway.base_url)) as api:
    tid = new_thread(api, "complex_workflow")
    code, events = run(api, tid, {"input": {"email": EMAILS[0]}})
    check("1 dispute paused for review", code == 200 and events[-1]["data"]["status"] == "interrupted", events[-1:])
    hold(tid)
    busy = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"}, headers=TEAM)
    check(
        "2 the decision is recorded while the thread is busy (409, resumes later)",
        busy.status_code == 409,
        busy.text[:200],
    )
    time.sleep(1.5)  # past the token's one-second TTL
    hold(tid, release=True)
    retried = api.post(f"/reviews/{tid}/decision", json={"decision": "approved"}, headers=TEAM)
    check("3 the retried decide is accepted (200)", retried.status_code == 200, retried.text[:200])
    # Non-vacuous: without renewal the expired token is refused and the run fails; here the reply goes once.
    last = data(api.get(f"/v1/threads/{tid}/runs"))[-1]
    check("3 the late resume finished instead of failing on the expired token", last["status"] == "done", last)
    values = data(api.get(f"/v1/threads/{tid}/state"))["values"]
    # Through the gateway the id is the mail provider's. Its log holds the expired token's refusal and the one send.
    rows = data(gateway.get("/v1/executions", params={"thread": tid, "tool": "send_reply", "pageSize": 10}))["data"]
    check(
        "3 the gateway refused the expired token once, and the renewed one sent the reply once",
        bool(values.get("sent")) and sorted(r.get("status") for r in rows) == ["denied", "ok"],
        {"sent": values.get("sent"), "rows": [(r.get("status"), r.get("runId")) for r in rows]},
    )

finish()
