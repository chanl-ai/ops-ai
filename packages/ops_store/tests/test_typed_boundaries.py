"""A model at the store's boundaries, by failure mode: a row with a column its model does not name leaves the store
anyway; an event whose payload is another kind than its name travels; a task started from a request fails unseen or
outlives the shutdown."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import create_async_engine

from ops_service_kit.http import Out
from ops_store import background
from ops_store.background import PROCESSES, MemoryHeartbeats
from ops_store.outbox import Event, KbChanged
from ops_store.rows import UnnamedColumns, one, rows

bases = sa.Table(
    "bases",
    sa.MetaData(),
    sa.Column("id", sa.String(32), primary_key=True),
    sa.Column("name", sa.String(64), nullable=False),
    sa.Column("secret", sa.String(64)),
)


class BaseOut(Out):
    id: str
    name: str


async def test_a_column_the_model_does_not_name_is_an_error(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rows.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(bases.metadata.create_all)
        await conn.execute(bases.insert(), [{"id": "kb1", "name": "Claims", "secret": "s"}])
        got = await rows(conn, sa.select(bases.c.id, bases.c.name), BaseOut)
        assert got == [BaseOut(id="kb1", name="Claims")]
        with pytest.raises(UnnamedColumns, match="secret"):
            await rows(conn, sa.select(bases), BaseOut)
        with pytest.raises(UnnamedColumns, match="secret"):
            await one(conn, sa.select(bases).where(bases.c.id == "kb1"), BaseOut)
        assert await one(conn, sa.select(bases.c.id, bases.c.name).where(bases.c.id == "none"), BaseOut) is None
    await engine.dispose()


def test_an_event_carries_only_the_payload_its_name_says() -> None:
    kb = KbChanged(id="kb1", name="Claims")
    assert Event(name="kb.changed", tenant_id="acme", team_id="ops", revision=3, payload=kb).key() == "kb1@3"
    with pytest.raises(ValidationError, match="cannot travel as"):
        Event(name="tool.module.published", tenant_id="acme", team_id="ops", revision=1, payload=kb)
    with pytest.raises(ValidationError):
        Event.model_validate(
            {"name": "kb.changed", "tenantId": "acme", "teamId": "ops", "revision": 1, "payload": {"kind": "nope"}}
        )


async def test_a_started_task_shows_its_failure_and_is_cancelled_at_shutdown() -> None:
    process = PROCESSES[0]
    beats = MemoryHeartbeats()
    cancelled = asyncio.Event()

    async def fails() -> None:
        raise RuntimeError("the hand-off was refused")

    async def waits() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    with pytest.raises(background.NoSupervisor):
        await background.start(waits(), key=process.key, store=beats)
    async with background.supervisor():
        await background.start(waits(), key=process.key, store=beats)
        await background.start(fails(), key=process.key, store=beats)
        for _ in range(100):
            if beats.beats:
                break
            await asyncio.sleep(0.01)
    assert cancelled.is_set(), "a task still running when the lifespan ends is cancelled, not left behind"
    report = background.report(await beats.read(), process.service, time.time(), detail=True)
    shown = next(r for r in report if r["key"] == process.key)
    assert shown["state"] == "stopped"
    assert shown["lastError"] == "RuntimeError: the hand-off was refused"
