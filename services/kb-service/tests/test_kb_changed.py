"""`kb.changed` on the outbox, by failure mode: a create, rename, recolour or delete that reports nothing, reports
twice, or reports a revision that does not rise, so another service's copy of the names misses or misorders it; a
change that is not one (the same name sent again, a description, a refused duplicate, a delete of nothing) reported as
one; and an event written apart from its row, so a change that rolls back still reports or a report that fails leaves
the change made."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_kb.store import knowledge
from ops_kb.store.knowledge import kb_outbox
from ops_store import isolation

from .test_bases_and_sources import data

BASE = {"name": "Claims", "owner": "maya@harborpine.example", "color": "blue"}


async def reported(engine: AsyncEngine, tenant: str) -> list[dict[str, Any]]:
    """The tenant's kb.changed events, oldest first, as the relay sends their payloads. Read in the tenant's scope, so
    SQL Server's tenant predicate passes the read as PostgreSQL's policy does."""
    q = (
        sa.select(kb_outbox.c.event_key, kb_outbox.c.payload)
        .where(kb_outbox.c.tenant_id == tenant, kb_outbox.c.name == "kb.changed")
        .order_by(kb_outbox.c.created_at, kb_outbox.c.id)
    )
    with isolation.tenant_wide("test: the tenant's kb.changed events", tenant_id=tenant):
        async with isolation.isolated_tx(engine) as c:
            return [{"key": r.event_key, **r.payload} for r in await c.execute(q)]


async def test_create_rename_recolour_and_delete_each_report_once_with_a_rising_revision(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)["id"]
    data(await client.patch(f"/v1/knowledge-bases/{kb}", json={"name": "Claims desk"}))
    data(await client.patch(f"/v1/knowledge-bases/{kb}", json={"color": "red"}))
    assert (await client.delete(f"/v1/knowledge-bases/{kb}")).status_code == 204
    seen = [
        {k: e[k] for k in ("key", "id", "name", "colour", "deleted", "revision")}
        for e in await reported(engine, tenant)
    ]
    assert seen == [
        {"key": f"{kb}@0", "id": kb, "name": "Claims", "colour": "blue", "deleted": False, "revision": 0},
        {"key": f"{kb}@1", "id": kb, "name": "Claims desk", "colour": "blue", "deleted": False, "revision": 1},
        {"key": f"{kb}@2", "id": kb, "name": "Claims desk", "colour": "red", "deleted": False, "revision": 2},
        {"key": f"{kb}@3", "id": kb, "name": "Claims desk", "colour": "red", "deleted": True, "revision": 3},
    ]


async def test_a_change_that_is_not_one_reports_nothing(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str
) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)["id"]
    data(await client.patch(f"/v1/knowledge-bases/{kb}", json={"name": "Claims", "color": "blue"}))
    data(await client.patch(f"/v1/knowledge-bases/{kb}", json={"description": "Claims handling rules"}))
    assert (await client.post("/v1/knowledge-bases", json=BASE)).status_code == 409
    assert (await client.delete("/v1/knowledge-bases/kb_missing")).status_code == 404
    assert [e["revision"] for e in await reported(engine, tenant)] == [0]


async def test_a_report_that_fails_leaves_no_change_made(
    client: httpx.AsyncClient, engine: AsyncEngine, tenant: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    kb = data(await client.post("/v1/knowledge-bases", json=BASE), 201)["id"]

    async def refused(*_: Any, **__: Any) -> None:
        raise RuntimeError("outbox refused the row")

    monkeypatch.setattr(knowledge, "add_event", refused)
    assert (await client.patch(f"/v1/knowledge-bases/{kb}", json={"name": "Claims desk"})).status_code == 500
    assert (await client.delete(f"/v1/knowledge-bases/{kb}")).status_code == 500
    monkeypatch.undo()
    assert data(await client.get(f"/v1/knowledge-bases/{kb}"))["name"] == "Claims"
    assert [e["revision"] for e in await reported(engine, tenant)] == [0]
