"""A check's batch, by failure mode, on PostgreSQL and SQL Server: two writers of one check (or an overlapping check)
leave two rows for one file version, and a writer whose place another moved still writes its batch."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_agents.store.batches import run_batch_rows, run_batches
from ops_agents.store.check_batches import CheckBatch, CheckRow, write_check
from ops_agents.store.poll_cursors import PollCursors
from ops_agents.store.tenancy import tenant_scope, tenant_tx
from ops_service_kit.http import Json
from ops_store.testing import NO_SQL_SERVER, sql_server_schema

WORKFLOW = "wf_invoices"
BINDING = f"files:{WORKFLOW}"


@pytest.fixture(params=["postgresql", "mssql"])
def url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        yield request.getfixturevalue("database_url")
        return
    with sql_server_schema("agents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as u:
        if u is None:
            pytest.skip(NO_SQL_SERVER)
        yield u


@pytest.fixture
async def engine(url: str) -> AsyncIterator[AsyncEngine]:
    e = create_async_engine(url)
    with tenant_scope(f"t-{uuid4().hex[:8]}"):
        yield e
    await e.dispose()


def _batch() -> CheckBatch:
    return CheckBatch(
        team_id="team_ap",
        workflow_id=WORKFLOW,
        version=3,
        mode="live",
        watch_id="wat_1",
        label="Supplier invoices, checked 24 Nov 09:00",
        checked_at="2026-11-24T09:00:00+00:00",
        created_by=f"trigger:files:{WORKFLOW}",
    )


def _row(key: str) -> CheckRow:
    return CheckRow(item_key=key, input={"fileId": key, "version": 1}, status="pending")


async def _written(engine: AsyncEngine) -> tuple[int, list[str]]:
    async with tenant_tx(engine) as c:
        batches = (await c.execute(sa.select(sa.func.count()).select_from(run_batches))).scalar_one()
        keys = (await c.execute(sa.select(run_batch_rows.c.item_key).order_by(run_batch_rows.c.item_key))).scalars()
        return int(batches), list(keys)


async def test_two_writers_of_one_check_leave_one_row_per_version(engine: AsyncEngine) -> None:
    # Two collectors of the same check at once, both from the place before it.
    rows = [_row("k1"), _row("k2")]
    first, second = await asyncio.gather(
        write_check(engine, binding_id=BINDING, watch_id="wat_1", expected=None, to="10", batch=_batch(), rows=rows),
        write_check(engine, binding_id=BINDING, watch_id="wat_1", expected=None, to="10", batch=_batch(), rows=rows),
    )
    # An overlapping check that read k2 again: only k3 is new.
    third = await write_check(
        engine,
        binding_id=BINDING,
        watch_id="wat_1",
        expected="10",
        to="12",
        batch=_batch(),
        rows=[_row("k2"), _row("k3")],
    )
    assert sorted(b is None for b in (first, second)) == [False, True]
    assert third is not None and third.total == 1
    assert await _written(engine) == (2, ["k1", "k2", "k3"])


async def test_a_writer_whose_place_moved_writes_no_batch(engine: AsyncEngine) -> None:
    moved = await write_check(
        engine, binding_id=BINDING, watch_id="wat_1", expected=None, to="5", batch=_batch(), rows=[_row("k1")]
    )
    stale = await write_check(
        engine, binding_id=BINDING, watch_id="wat_1", expected=None, to="9", batch=_batch(), rows=[_row("k9")]
    )
    at = await PollCursors(engine).get(BINDING)
    assert moved is not None and stale is None
    assert at is not None and (at.source, at.cursor) == ("wat_1", "5")
    assert await _written(engine) == (1, ["k1"])


async def test_a_group_past_500_rows_opens_part_2_and_held_files_are_taken_once(engine: AsyncEngine) -> None:
    from ops_agents.store.batches import MAX_ROWS, Batches  # noqa: PLC0415
    from ops_agents.store.waiting_files import WaitingFiles  # noqa: PLC0415

    batches, waiting = Batches(engine), WaitingFiles(engine)

    async def opened() -> Any:
        return await batches.open_group(
            team_id="team_ap", workflow_id=WORKFLOW, version=3, mode="live", watch_id="wat_1",
            checked_at="2026-11-24T09:00:00+00:00", created_by=f"trigger:files:{WORKFLOW}", group_key="g-batch001",
            group_name="Batch001", group_parts={"batch": "Batch001"},
        )  # fmt: skip

    files: list[Json] = [
        {"itemKey": f"k{i}", "input": {"fileId": f"fil_{i}", "version": 1}} for i in range(MAX_ROWS + 1)
    ]
    first = await opened()
    added, left = await batches.add_rows(first.id, files)
    again = await batches.add_rows(first.id, files[:3])
    second = await opened()
    added_2, _ = await batches.add_rows(second.id, left)
    assert (added, len(left), again, added_2) == (MAX_ROWS, 1, (0, []), 1)
    assert (second.part, second.group_name) == (2, "Batch001") and (await opened()).id == second.id
    held: list[Json] = [{"itemKey": "w1", "input": {}}, {"itemKey": "w2", "input": {}}]

    async def hold() -> int:
        return await waiting.hold(
            team_id="team_ap", workflow_id=WORKFLOW, group_key="g-b2", group_name="Batch002", files=held
        )

    assert (await hold(), await hold()) == (2, 0)
    assert [(g.group_name, g.held) for g in await waiting.held(WORKFLOW)] == [("Batch002", 2)]
    taken, twice = await waiting.take(WORKFLOW, "g-b2"), await waiting.take(WORKFLOW, "g-b2")
    assert ([t.item_key for t in taken], twice, await waiting.held(WORKFLOW)) == (["w1", "w2"], [], [])
