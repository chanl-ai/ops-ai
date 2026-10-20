# ruff: noqa: E501
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportOptionalSubscript=false, reportOperatorIssue=false
# Printed lines are the experiment's record and stay whole; LangGraph's compiled graph and asyncpg records are partly untyped.
"""Experiment 4: how checkpoints grow, on a scratch database, with the model stubbed (no tokens).

  uv run python experiments/e4_checkpoint_growth.py            # all parts, 50 cases
  uv run python experiments/e4_checkpoint_growth.py --cases 10  # faster

Creates database `ops_e4` next to the Runtime's (never the shared `ops_runtime`), migrates it, and runs the dispute
workflow through E0's checkpointer with timing around every checkpoint write.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import statistics
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
from langgraph.types import Command

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.models import Facts, Grade
from ops_agents.graphs.registry import build_graphs
from ops_checkpointer import open_saver
from tests.knowledge_fixture import KeywordPassageStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.conftest import SEED, scripted_model  # noqa: E402

ADMIN = "postgresql://ops:ops@localhost:5477/ops_runtime"
SCRATCH_DB = "ops_e4"
SCRATCH = f"postgresql+asyncpg://ops:ops@localhost:5477/{SCRATCH_DB}"
DSN = f"postgresql://ops:ops@localhost:5477/{SCRATCH_DB}"
DRAFT = (
    "Thank you for reporting the charge. We have reviewed your statement, the merchant receipt and your location "
    "record. The receipt shows a card-not-present purchase while you were in another city, which supports your "
    "dispute. We have opened case DSP-2210 and posted a provisional credit while we investigate; you will hear from "
    "us within 10 business days."
) * 2
WORDS = [
    "statement",
    "merchant",
    "charge",
    "refund",
    "card",
    "dispute",
    "receipt",
    "amount",
    "posted",
    "pending",
    "halifax",
    "moncton",
    "online",
    "order",
    "dock",
    "cable",
    "invoice",
    "reference",
    "account",
    "balance",
    "transfer",
]


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def unique_text(seed: int, size: int) -> str:
    """Text that does not repeat, so TOAST compression cannot hide its size the way it hides a repeated sentence."""
    rng = random.Random(seed)
    parts: list[str] = []
    total = 0
    while total < size:
        w = f"{rng.choice(WORDS)}{rng.randint(0, 99999)}"
        parts.append(w)
        total += len(w) + 1
    return " ".join(parts)[:size]


class StubModels:
    """Canned workflow model outputs. In reference mode an attachment's `text` is `file:<id>`, read from the files
    store here the way the real extract port would fetch it through the tool gateway."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    async def classify(self, text: str, labels: list[str]) -> str:
        return labels[0]

    async def extract(self, category: str, name: str, text: str) -> Facts:
        body = self.files[text[5:]] if text.startswith("file:") else text
        return Facts(summary=f"{name}: {body[:80]}", amount="$212.40", merchant="Harbourline Electronics")

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        return DRAFT

    async def grade(self, email: str, draft: str) -> Grade:
        return Grade(score=0.9, feedback="Clear and complete.")

    async def extract_records(self, schema: str, text: str) -> list[dict[str, Any]]:
        return []


@dataclass
class Timings:
    puts: list[tuple[float, int]] = field(default_factory=list[tuple[float, int]])
    writes: list[tuple[float, int, int]] = field(default_factory=list[tuple[float, int, int]])


def pct(values: list[float], q: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


# The scenario being measured; instrument() appends to whichever Timings is here.
CURRENT: list[Timings] = [Timings()]


def instrument(saver: Any) -> None:
    """Wraps the saver once; each scenario swaps CURRENT so its own writes are timed and nothing is wrapped twice.
    The serialised size is computed outside the timed region."""
    put: Callable[..., Awaitable[Any]] = saver.aput
    put_writes: Callable[..., Awaitable[Any]] = saver.aput_writes

    async def timed_put(config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        size = len(saver.serde.dumps_typed(checkpoint)[1])
        started = time.perf_counter()
        r = await put(config, checkpoint, metadata, new_versions)
        CURRENT[0].puts.append(((time.perf_counter() - started) * 1000, size))
        return r

    async def timed_writes(config: Any, writes: Any, task_id: str, task_path: str = "") -> Any:
        size = sum(len(saver.serde.dumps_typed(v)[1]) for _, v in writes)
        started = time.perf_counter()
        r = await put_writes(config, writes, task_id, task_path)
        CURRENT[0].writes.append(((time.perf_counter() - started) * 1000, len(writes), size))
        return r

    saver.aput = timed_put
    saver.aput_writes = timed_writes


def make_email(case: int, attachments: int, size: int, files: dict[str, str] | None) -> dict[str, Any]:
    atts: list[dict[str, str]] = []
    for i in range(attachments):
        text = unique_text(case * 1000 + i, size)
        if files is not None:
            fid = f"f{case}_{i}"
            files[fid] = text
            atts.append({"name": f"att-{i:02d}.txt", "text": f"file:{fid}"})
        else:
            atts.append({"name": f"att-{i:02d}.txt", "text": text})
    return {
        "sender": f"customer{case}@example.com",
        "subject": f"Disputed charge, case {case}",
        "body": "Please review the attached evidence.",
        "attachments": atts,
    }


async def scratch_db() -> None:
    admin = await asyncpg.connect(ADMIN)
    await admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {SCRATCH_DB}")
    await admin.close()
    env = {**os.environ, "OPS_DATABASE_URL": SCRATCH}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, check=True, capture_output=True, env=env
    )


def deps(files: dict[str, str]) -> GraphDeps:
    catalog = load_catalog(SEED)
    ports = KernelPorts(scripted_model(), LocalToolExecutor(catalog), KeywordPassageStore(catalog))
    return GraphDeps(catalog, ports, StubModels(files), LocalReplySender(), "stub")


async def run_case(graph: Any, thread: str, email: dict[str, Any]) -> None:
    cfg: Any = {"configurable": {"thread_id": thread}, "max_concurrency": 4}
    await graph.ainvoke({"email": email}, cfg)
    await graph.ainvoke(Command(resume={"decision": "approved"}), cfg)


async def stats(conn: asyncpg.Connection, prefix: str) -> dict[str, Any]:
    cp = await conn.fetchrow(
        "SELECT count(*) n, count(DISTINCT thread_id) t,"
        " coalesce(sum(pg_column_size(checkpoint) + pg_column_size(metadata_blob) + pg_column_size(metadata)), 0) stored,"
        " coalesce(sum(octet_length(checkpoint) + octet_length(metadata_blob)), 0) raw"
        " FROM ops_checkpoints WHERE thread_id LIKE $1",
        prefix + "%",
    )
    wr = await conn.fetchrow(
        "SELECT count(*) n, coalesce(sum(pg_column_size(blob)), 0) stored, coalesce(sum(octet_length(blob)), 0) raw FROM ops_checkpoint_writes WHERE thread_id LIKE $1",
        prefix + "%",
    )
    return {
        "threads": cp["t"],
        "cp_rows": cp["n"],
        "cp_stored": cp["stored"],
        "cp_raw": cp["raw"],
        "w_rows": wr["n"],
        "w_stored": wr["stored"],
        "w_raw": wr["raw"],
    }


async def table_sizes(conn: asyncpg.Connection) -> str:
    rows = await conn.fetch(
        "SELECT relname, pg_total_relation_size(oid) total, pg_indexes_size(oid) idx FROM pg_class WHERE relname IN ('ops_checkpoints', 'ops_checkpoint_writes') ORDER BY relname"
    )
    return "; ".join(f"{r['relname']} {r['total'] / 1e6:.2f} MB (indexes {r['idx'] / 1e6:.2f} MB)" for r in rows)


def summary(label: str, s: dict[str, Any], t: Timings) -> dict[str, Any]:
    put_ms = [x[0] for x in t.puts]
    n = max(1, s["threads"])
    row = {
        "scenario": label,
        "cp_rows": s["cp_rows"] / n,
        "w_rows": s["w_rows"] / n,
        "raw_kb": (s["cp_raw"] + s["w_raw"]) / n / 1024,
        "stored_kb": (s["cp_stored"] + s["w_stored"]) / n / 1024,
        "cp_raw_kb": s["cp_raw"] / n / 1024,
        "p50": pct(put_ms, 50),
        "p95": pct(put_ms, 95),
        "w_p95": pct([x[0] for x in t.writes], 95),
        "largest_kb": max((x[1] for x in t.puts), default=0) / 1024,
    }
    out(
        f"{label}: {s['threads']} threads; per thread {row['cp_rows']:.0f} checkpoint rows, {row['w_rows']:.0f} write rows; "
        f"{row['raw_kb']:.0f} KB raw ({row['cp_raw_kb']:.0f} KB in checkpoints), {row['stored_kb']:.0f} KB stored after TOAST compression; "
        f"largest checkpoint {row['largest_kb']:.0f} KB; checkpoint write p50 {row['p50']:.2f} ms p95 {row['p95']:.2f} ms; task writes p95 {row['w_p95']:.2f} ms"
    )
    return row


async def per_step(conn: asyncpg.Connection, thread: str) -> None:
    rows = await conn.fetch(
        "SELECT checkpoint_id, metadata->>'step' step, metadata->>'source' source, octet_length(checkpoint) raw, pg_column_size(checkpoint) stored FROM ops_checkpoints WHERE thread_id = $1 ORDER BY checkpoint_id",
        thread,
    )
    writes = {
        r["checkpoint_id"]: (r["n"], r["raw"])
        for r in await conn.fetch(
            "SELECT checkpoint_id, count(*) n, sum(octet_length(blob)) raw FROM ops_checkpoint_writes WHERE thread_id = $1 GROUP BY checkpoint_id",
            thread,
        )
    }
    out(f"per step for {thread} (step, source, checkpoint KB raw / stored, task writes against it: rows / KB raw):")
    for r in rows:
        w = writes.get(r["checkpoint_id"], (0, 0))
        out(
            f"  step {r['step']:>3} {r['source']:<6} {r['raw'] / 1024:7.1f} / {r['stored'] / 1024:6.1f} KB   writes {w[0]:>3} / {w[1] / 1024:6.1f} KB"
        )


async def scenario(
    saver: Any, label: str, prefix: str, *, cases: int, attachments: int, size: int, refs: bool, concurrency: int = 1
) -> dict[str, Any]:
    files: dict[str, str] = {}
    t = CURRENT[0] = Timings()
    graph = build_graphs(deps(files), saver)["complex_workflow"]
    emails = [make_email(i, attachments, size, files if refs else None) for i in range(cases)]
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int) -> None:
        async with sem:
            await run_case(graph, f"{prefix}{i:03d}", emails[i])

    started = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(cases)))
    elapsed = time.perf_counter() - started
    conn = await asyncpg.connect(DSN)
    s = await stats(conn, prefix)
    await conn.close()
    row = summary(label, s, t)
    row["elapsed_s"] = elapsed
    return row


async def pg_counters(conn: asyncpg.Connection) -> dict[str, float]:
    wal = await conn.fetchrow("SELECT wal_records, wal_bytes FROM pg_stat_wal")
    io = await conn.fetchrow("SELECT coalesce(sum(writes), 0) w, coalesce(sum(extends), 0) e FROM pg_stat_io")
    db = await conn.fetchrow("SELECT xact_commit, tup_inserted FROM pg_stat_database WHERE datname = $1", SCRATCH_DB)
    return {
        "wal_records": wal["wal_records"],
        "wal_bytes": float(wal["wal_bytes"]),
        "io_writes": float(io["w"]) + float(io["e"]),
        "commits": db["xact_commit"],
        "inserts": db["tup_inserted"],
    }


def pg_cpu_usec() -> int:
    """Cumulative CPU time of the PostgreSQL container from its cgroup; a delta over wall time gives utilisation."""
    r = subprocess.run(
        ["docker", "exec", "ops-runtime-postgres-1", "cat", "/sys/fs/cgroup/cpu.stat"],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(next(line.split()[1] for line in r.stdout.splitlines() if line.startswith("usage_usec")))


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cases", type=int, default=50)
    args = ap.parse_args()
    await scratch_db()
    out(f"scratch database {SCRATCH_DB} created and migrated")
    table: list[dict[str, Any]] = []
    async with open_saver(SCRATCH, tenant_id="e4", team_id="e4", max_size=24) as saver:
        instrument(saver)
        conn = await asyncpg.connect(DSN)

        out(f"\n## 1. Payloads in state: {args.cases} cases x 20 attachments x 2 KB")
        table.append(
            await scenario(
                saver, "payloads, 20 x 2 KB", "pay_", cases=args.cases, attachments=20, size=2048, refs=False
            )
        )
        await per_step(conn, "pay_000")
        out(f"tables: {await table_sizes(conn)}")

        out(f"\n## 2. References in state: {args.cases} cases x 20 attachments, ids only")
        table.append(
            await scenario(saver, "references, 20 ids", "ref_", cases=args.cases, attachments=20, size=2048, refs=True)
        )
        await per_step(conn, "ref_000")

        out(
            "\n## 3. Serialiser: msgpack (what LangGraph stores) vs JSON, for one finished payload thread's last checkpoint"
        )
        last = await conn.fetchrow(
            "SELECT type, checkpoint FROM ops_checkpoints WHERE thread_id = 'pay_000' ORDER BY checkpoint_id DESC LIMIT 1"
        )
        decoded = saver.serde.loads_typed((last["type"], bytes(last["checkpoint"])))
        as_json = len(json.dumps(decoded, default=str).encode())
        out(
            f"stored type {last['type']}: {len(last['checkpoint']) / 1024:.1f} KB; the same object as JSON: {as_json / 1024:.1f} KB"
        )
        values = decoded.get("channel_values", {})
        out(f"channels in that checkpoint: {sorted(values)}")

        out("\n## 4. Prune finished threads (keep_latest), then VACUUM, REINDEX, VACUUM FULL")
        before = await stats(conn, "")
        sizes_before = await table_sizes(conn)
        threads = [r["thread_id"] for r in await conn.fetch("SELECT DISTINCT thread_id FROM ops_checkpoints")]
        started = time.perf_counter()
        await saver.aprune(threads)
        prune_s = time.perf_counter() - started
        after = await stats(conn, "")
        out(
            f"before: {before['cp_rows']} checkpoint rows, {before['w_rows']} write rows, {(before['cp_raw'] + before['w_raw']) / 1e6:.2f} MB raw; {sizes_before}"
        )
        out(
            f"after prune ({prune_s * 1000:.0f} ms for {len(threads)} threads): {after['cp_rows']} checkpoint rows, {after['w_rows']} write rows, {(after['cp_raw'] + after['w_raw']) / 1e6:.2f} MB raw; {await table_sizes(conn)}"
        )
        await conn.execute("VACUUM ops_checkpoints, ops_checkpoint_writes")
        out(f"after VACUUM: {await table_sizes(conn)}")
        await conn.execute("REINDEX TABLE ops_checkpoints")
        await conn.execute("REINDEX TABLE ops_checkpoint_writes")
        out(f"after REINDEX: {await table_sizes(conn)}")
        await conn.execute("VACUUM FULL ops_checkpoints, ops_checkpoint_writes")
        out(f"after VACUUM FULL: {await table_sizes(conn)}")

        out("\n## 5. Load: 100 cases, 20 at a time, payloads in state")
        c0, cpu0 = await pg_counters(conn), pg_cpu_usec()
        row = await scenario(
            saver, "payloads, 20 concurrent", "load_", cases=100, attachments=20, size=2048, refs=False, concurrency=20
        )
        c1, cpu1 = await pg_counters(conn), pg_cpu_usec()
        secs = row["elapsed_s"]
        out(
            f"load: {secs:.1f} s for 100 cases; PostgreSQL CPU {(cpu1 - cpu0) / 1e6 / secs * 100:.0f}% of one core; commits {(c1['commits'] - c0['commits']) / secs:.0f}/s; "
            f"rows inserted {(c1['inserts'] - c0['inserts']) / secs:.0f}/s; WAL {(c1['wal_bytes'] - c0['wal_bytes']) / 1e6 / secs:.1f} MB/s "
            f"({(c1['wal_records'] - c0['wal_records']) / secs:.0f} records/s); block writes and extends {(c1['io_writes'] - c0['io_writes']) / secs:.0f}/s"
        )
        table.append(row)

        out("\n## 6. Knee: 3 cases, 20 attachments each, growing attachment size, payloads in state")
        knee: float | None = None
        for kb in (2, 10, 25, 50, 100, 200, 400, 800):
            r = await scenario(
                saver, f"knee {kb} KB x 20", f"knee{kb}_", cases=3, attachments=20, size=kb * 1024, refs=False
            )
            if knee is None and r["p95"] > 50:
                knee = r["largest_kb"]
            table.append(r)
        out(
            f"first size with a p95 checkpoint write over 50 ms: {f'{knee:.0f} KB checkpoint' if knee else 'not reached up to 800 KB attachments'}"
        )
        await conn.close()

    out("\n## Table")
    out(
        "| Scenario | Checkpoint rows / thread | Write rows / thread | KB / thread raw | KB / thread stored | Largest checkpoint KB | p95 checkpoint write ms |"
    )
    out("|---|---|---|---|---|---|---|")
    for r in table:
        out(
            f"| {r['scenario']} | {r['cp_rows']:.0f} | {r['w_rows']:.0f} | {r['raw_kb']:.0f} | {r['stored_kb']:.0f} | {r['largest_kb']:.0f} | {r['p95']:.2f} |"
        )


if __name__ == "__main__":
    asyncio.run(main())
