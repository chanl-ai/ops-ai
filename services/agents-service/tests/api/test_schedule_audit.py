"""Schedule audit entries, by failure mode: a save or a clear leaves no entry or the wrong words (old and new in
words), a refused save leaves one anyway, and the relay delivers an entry without its team in the token. Through the
real app and database; the platform service is a recording poster at the edge."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.outbox import agents_outbox, outbox_relay
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from tests.api.test_schedule_routes import EVERY_15, definition, url
from tests.engine.test_lifecycle_rights import (  # noqa: F401
    BUILDER,
    TENANT,
    stack,  # pyright: ignore[reportUnusedImport]
)


async def entries(engine: AsyncEngine) -> list[dict[str, Any]]:
    with tenant_scope(TENANT):
        async with tenant_tx(engine) as c:
            rows = (await c.execute(sa.select(agents_outbox).order_by(agents_outbox.c.created_at))).mappings().all()
    return [dict(r) for r in rows]


async def made(c: AsyncClient, wid: str) -> None:
    res = await c.post("/v1/workflows/definitions", json={"definition": definition(wid)}, headers=BUILDER)
    assert res.status_code < 300, res.text


async def test_a_save_and_a_clear_each_leave_one_entry_with_old_and_new_in_words(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, engine = stack
    await made(c, "audited")
    hourly: dict[str, Any] = {"kind": "hourly", "every": 1}
    for rule in (EVERY_15, hourly):
        assert (await c.put(url("audited"), json={"rule": rule}, headers=BUILDER)).status_code == 200
    assert (await c.delete(url("audited"), headers=BUILDER)).status_code == 204
    got = await entries(engine)
    payloads = [r["payload"] for r in got]
    assert [(p["action"], p["targetId"]) for p in payloads] == [
        ("workflow.schedule.save", "audited"),
        ("workflow.schedule.save", "audited"),
        ("workflow.schedule.clear", "audited"),
    ]
    assert [p["detail"]["summary"] for p in payloads] == [
        "Set the schedule of Held wires to Every 15 minutes from 00:00, UTC",
        "Changed the schedule of Held wires from Every 15 minutes from 00:00, UTC to Every hour",
        "Cleared the schedule of Held wires; it was Every hour",
    ]
    assert {r["name"] for r in got} == {"audit.recorded"} and all(r["actor"] for r in got)


async def test_a_refused_save_leaves_no_entry(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    c, engine = stack
    await made(c, "refused")
    bad = await c.put(url("refused"), json={"rule": {"kind": "every", "every": 2, "unit": "minutes"}}, headers=BUILDER)
    assert bad.status_code == 422
    assert (await c.delete(url("refused"), headers=BUILDER)).status_code == 404
    assert await entries(engine) == []


class Platform:
    """platform-service's internal audit route, as the relay posts to it."""

    def __init__(self) -> None:
        self.posted: list[tuple[str, dict[str, Any], str, str]] = []

    async def post(self, path: str, body: dict[str, Any], *, tenant: str, team: str) -> dict[str, Any]:
        self.posted.append((path, body, tenant, team))
        return {}


async def test_the_relay_delivers_the_entry_to_platform_with_the_team_in_the_token(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, engine = stack
    await made(c, "relayed")
    assert (await c.put(url("relayed"), json={"rule": EVERY_15}, headers=BUILDER)).status_code == 200
    platform = Platform()
    assert await outbox_relay(engine, {"platform": platform}).once() == 1
    [(path, body, tenant, team)] = platform.posted
    assert (path, tenant) == ("/v1/audit-events", TENANT) and team and "teamId" not in body
    assert body["name"] == "audit.recorded" and body["payload"]["action"] == "workflow.schedule.save"
    assert await outbox_relay(engine, {"platform": platform}).once() == 0
