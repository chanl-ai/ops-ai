"""The two-person rule never binds an Admin of the team, through the real start route, worker and decision route:
an Admin's own run holds at its review like anyone's, and her own click decides it, where a Builder's is refused."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.engine.test_lifecycle import NoTools, drain, worker
from tests.engine.test_lifecycle_rights import (
    person,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    unowned_live,
)

STRICT = {"requesterMayDecide": False}


async def _waiting_run(c: AsyncClient, engine: AsyncEngine, who: dict[str, str], key: str) -> str:
    started = await c.post(
        "/v1/runs", json={"workflowId": "refunds", "mode": "live", "input": {"amount": 250}, "runKey": key}, headers=who
    )
    assert started.status_code == 202, started.text
    run_id = str(started.json()["data"]["runId"])
    await drain(worker(engine, NoTools()))
    run: dict[str, Any] = (await c.get(f"/v1/runs/{run_id}", headers=who)).json()["data"]
    assert run["status"] == "waiting", run
    return run_id


async def test_an_admin_decides_her_own_run_under_the_two_person_rule(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    builder = person("jo", "team_ops", "builder", policies=STRICT)
    his = await _waiting_run(c, engine, builder, "jo")
    refused = await c.post(f"/reviews/{his}/decision", json={"decision": "approved"}, headers=builder)
    assert refused.status_code == 403, refused.text
    admin = person("priya", "team_ops", "admin", policies=STRICT)
    hers = await _waiting_run(c, engine, admin, "priya")
    decided = await c.post(f"/reviews/{hers}/decision", json={"decision": "approved"}, headers=admin)
    assert decided.status_code == 200, decided.text
