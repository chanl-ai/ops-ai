# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false
# asyncpg records and E4's helpers are partly untyped.
"""Whole-state checkpoints against channel values stored once per version, on E4's dispute scenarios.

Runs each scenario through both savers on a fresh scratch database (`ops_blobsize`, dropped and recreated), with E4's
stubbed models; no model calls. Bytes per thread count everything a thread stores: checkpoint rows, pending writes
and, for the variant, its channel blobs; raw is `octet_length`, stored is after TOAST (`pg_column_size`). Write
latency is p95 of `aput`, which for the variant includes its blob insert; read latency is p95 of `aget_tuple`.

  make -C services/agents-service db-up && uv run python experiments/checkpoint_channel_blobs.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg  # pyright: ignore[reportMissingTypeStubs]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from langgraph.checkpoint.conformance import checkpointer_test, validate  # noqa: E402

from experiments import e4_checkpoint_growth as e4  # noqa: E402
from experiments.channel_blob_saver import BLOB_SCHEMA, ChannelBlobSaver  # noqa: E402
from ops_checkpointer import RLS_ROLE, AsyncpgSaver, create_pool  # noqa: E402

DB = "ops_blobsize"
DSN = f"postgresql://ops:ops@localhost:5477/{DB}"
# (label, cases, attachments, bytes per attachment, attachments held as file references)
SCENARIOS: list[tuple[str, int, int, int, bool]] = [
    ("Payloads, 20 x 2 KB", 50, 20, 2048, False),
    ("References, 20 ids", 50, 20, 2048, True),
    ("Payloads, 20 x 50 KB", 20, 20, 51200, False),
]


async def fresh_database() -> None:
    admin: Any = await asyncpg.connect("postgresql://ops:ops@localhost:5477/postgres")  # pyright: ignore[reportUnknownMemberType]
    await admin.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {DB}")
    await admin.close()
    env = {**os.environ, "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:5477/{DB}"}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, capture_output=True, env=env
    )
    conn: Any = await asyncpg.connect(DSN)  # pyright: ignore[reportUnknownMemberType]
    for stmt in BLOB_SCHEMA:
        await conn.execute(stmt)
    await conn.close()


async def bytes_per_thread(prefix: str, cases: int) -> tuple[float, float]:
    conn: Any = await asyncpg.connect(DSN)  # pyright: ignore[reportUnknownMemberType]
    raw = stored = 0
    for table, cols in (
        ("ops_checkpoints", ["checkpoint", "metadata_blob"]),
        ("ops_checkpoint_writes", ["blob"]),
        ("ops_checkpoint_blobs", ["blob"]),
    ):
        r = " + ".join(f"coalesce(sum(octet_length({c})), 0)" for c in cols)
        s = " + ".join(f"coalesce(sum(pg_column_size({c})), 0)" for c in cols)
        row = await conn.fetchrow(f"SELECT {r} raw, {s} stored FROM {table} WHERE thread_id LIKE $1", f"{prefix}%")
        raw += int(row["raw"])
        stored += int(row["stored"])
    await conn.close()
    return raw / cases / 1024, stored / cases / 1024


async def read_times(saver: Any, prefix: str, cases: int) -> list[float]:
    """Each thread's latest checkpoint read three times, as a resume or a state view would read it."""
    times: list[float] = []
    for _ in range(3):
        for i in range(cases):
            started = time.perf_counter()
            await saver.aget_tuple({"configurable": {"thread_id": f"{prefix}{i:03d}", "checkpoint_ns": ""}})
            times.append((time.perf_counter() - started) * 1000)
    return times


async def main() -> None:
    await fresh_database()
    pool = await create_pool(DSN, max_size=24)
    savers = {
        "whole state": AsyncpgSaver(pool, tenant_id="e4", team_id="e4", role=RLS_ROLE),
        "per version": ChannelBlobSaver(pool, tenant_id="e4", team_id="e4", role=RLS_ROLE),
    }

    # The variant must pass LangGraph's own conformance suite before its numbers mean anything.
    @checkpointer_test(name="ChannelBlobSaver")
    async def fresh() -> Any:
        yield ChannelBlobSaver(pool, tenant_id=f"conf-{time.time_ns()}", team_id="team", role=RLS_ROLE)

    report = (await validate(fresh)).to_dict()
    passed = sum(v["tests_passed"] for v in report["results"].values())
    failed = sum(v["tests_failed"] for v in report["results"].values())
    level = report["conformance_level"]
    e4.out(f"Conformance on the variant: {passed} passed, {failed} failed, {level}")
    for saver in savers.values():
        e4.instrument(saver)
    e4.out(f"Scratch database {DB}; E4's dispute workflow with stubbed models; no model calls.")
    e4.out("| Scenario | Saver | KB / thread raw | KB / thread stored | p95 write ms | p95 read ms |")
    e4.out("|---|---|---|---|---|---|")
    for n, (label, cases, attachments, size, refs) in enumerate(SCENARIOS):
        for i, (name, saver) in enumerate(savers.items()):
            prefix = f"s{n}{'wb'[i]}_"
            row = await e4.scenario(saver, label, prefix, cases=cases, attachments=attachments, size=size, refs=refs)
            raw, stored = await bytes_per_thread(prefix, cases)
            reads = await read_times(saver, prefix, cases)
            e4.out(f"| {label} | {name} | {raw:,.0f} | {stored:,.0f} | {row['p95']:.2f} | {e4.pct(reads, 95):.2f} |")
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
