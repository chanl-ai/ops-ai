# ruff: noqa: E501
# Printed lines are the experiment's record and stay whole.
"""Experiment 5: durable SLA timers for human steps, fired by a poller on a real Runtime process.

Needs `make db-up` and `make migrate`. For each poll interval (1 s, then 5 s) it starts a Runtime on :8724 with
OPS_TIMER_POLL_SECONDS set, then:
  1. starts one review with sla=2s, warnAt=1s, onTimeout=escalate and prints its SLA events and timers;
  2. starts 12 reviews whose warnings fall due across 6 s and reports due-to-fired latency from the database clock;
  3. on a scratch database `ops_e5` that nothing else uses, with no timer due, counts that database's transactions and
     row writes for 20 s with a Runtime polling at 1 s, at 5 s, and with no Runtime, to show the idle poller's load.

  OPENAI_API_KEY=... uv run python experiments/e5_timers_and_sla.py
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / ".logs"
PORT = 8724
EMAIL: dict[str, Any] = json.loads((ROOT / "tests" / "fixtures" / "seed" / "dispute_emails.json").read_text())[0]
IDLE_SECONDS = 20


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def sql(query: str, db: str = "ops_runtime") -> list[str]:
    r = subprocess.run(
        ["docker", "exec", "ops-runtime-postgres-1", "psql", "-U", "ops", "-d", db, "-tAc", query],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in r.stdout.strip().splitlines() if line]


def workflow(**human: Any) -> dict[str, Any]:
    return {
        "entry": "human",
        "nodes": [
            {"id": "human", "kind": "human", "config": {"group": "tier1", **human}},
            {
                "id": "decide",
                "kind": "condition",
                "config": {"rule": "decision", "approved": "done", "rejected": "close"},
            },
            {"id": "done", "kind": "end", "config": {"status": "replied"}},
            {"id": "close", "kind": "end", "config": {"status": "closed"}},
        ],
        "edges": [{"source": "human", "target": "decide"}],
    }


def spawn(poll: float, db: str = "ops_runtime") -> subprocess.Popen[bytes]:
    LOGS.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "PYDANTIC_AI_NO_BANNER": "1",
        "OPS_PORT": str(PORT),
        "OPS_TIMER_POLL_SECONDS": str(poll),
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:5477/{db}",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "ops_agents.api"],
        cwd=ROOT,
        env=env,
        stdout=(LOGS / "e5.log").open("ab"),
        stderr=subprocess.STDOUT,
    )
    for _ in range(80):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    proc.kill()
    raise SystemExit(f"Runtime did not come up on :{PORT}")


def start(c: httpx.Client, name: str, **human: Any) -> str:
    r = c.post(f"/v1/graphs/{name}/versions", json={"definition": workflow(**human)})
    r.raise_for_status()
    tid = str(c.post("/v1/threads", json={"graph": name, "metadata": {"source": "e5"}}).json()["data"]["threadId"])
    with c.stream("POST", f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL}}) as s:
        "".join(s.iter_text())
    return tid


def escalation(c: httpx.Client) -> None:
    tid = start(
        c, "e5_escalate", sla="2s", warnAt="1s", onTimeout="escalate", escalateTo="supervisors", maxWaitDays=6 / 86400
    )
    out(f"thread {tid}: review raised to tier1, sla=2s warnAt=1s onTimeout=escalate escalateTo=supervisors maxWait=6s")
    time.sleep(8)
    s = c.get(f"/v1/threads/{tid}/state").json()["data"]
    for e in s["sla"]["events"]:
        out(f"  event {e['event']:<15} {json.dumps(e['data'])}")
    for t in s["sla"]["timers"]:
        out(f"  timer {t['kind']:<8} {t['state']:<9} due {t['dueAt'][11:23]} fired {(t['firedAt'] or '-')[11:23]}")
    out(f"  final status={s['values'].get('status')} decision={json.dumps(s['values'].get('decision'))}")


def latency(c: httpx.Client) -> list[float]:
    tids = [start(c, f"e5_latency_{i}", sla="1h", warnAt=f"{1 + i * 0.5}s") for i in range(12)]
    time.sleep(10)
    ids = ",".join(f"'{t}'" for t in tids)
    rows = sql(
        f"select extract(epoch from fired_at - due_at) from timers where thread_id in ({ids}) and kind = 'warn' and fired_at is not null"
    )
    return [float(r) for r in rows]


SCRATCH = "ops_e5"


def scratch_db() -> None:
    """A database nothing else uses, so its counters are this Runtime's alone. Migrated to head like the real one."""
    if not sql(f"select 1 from pg_database where datname = '{SCRATCH}'", db="postgres"):
        sql(f"create database {SCRATCH}", db="postgres")
    env = {**os.environ, "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:5477/{SCRATCH}"}
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True)


def counters() -> tuple[int, int, int]:
    """Transactions, rows read by index or scan, and rows written, for the scratch database only."""
    row = sql(
        "select xact_commit + xact_rollback, tup_returned + tup_fetched, tup_inserted + tup_updated + tup_deleted"
        f" from pg_stat_database where datname = '{SCRATCH}'"
    )[0]
    xacts, reads, writes = (int(v) for v in row.split("|"))
    return xacts, reads, writes


def idle_load(poll: float | None) -> tuple[int, int, int]:
    proc = spawn(poll or 0, db=SCRATCH) if poll is not None else None
    try:
        time.sleep(3)  # past start-up, which seeds the workflow definitions
        a = counters()
        time.sleep(IDLE_SECONDS)
        b = counters()
    finally:
        if proc is not None:
            proc.terminate()
            proc.wait(timeout=10)
    return b[0] - a[0], b[1] - a[1], b[2] - a[2]


def main() -> None:
    for poll in (1.0, 5.0):
        out(f"\n## Poll interval {poll:.0f} s")
        proc = spawn(poll)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{PORT}", timeout=60) as c:
                if poll == 1.0:
                    out("### Escalation, then max wait")
                    escalation(c)
                lat = latency(c)
                out(
                    f"### Due-to-fired latency over {len(lat)} warnings: min {min(lat):.2f} s, median {statistics.median(lat):.2f} s, max {max(lat):.2f} s"
                )
        finally:
            proc.terminate()
            proc.wait(timeout=10)

    out(f"\n## Idle load on {SCRATCH}, {IDLE_SECONDS} s, no timer due (transactions, rows read, rows written)")
    scratch_db()
    for label, poll in (
        ("poller every 1 s", 1.0),
        ("poller every 5 s", 5.0),
        ("poller off", 0.0),
        ("no Runtime", None),
    ):
        x, rd, w = idle_load(poll)
        out(f"  {label:<17} {x:>5} transactions  {rd:>6} rows read  {w:>3} rows written")


if __name__ == "__main__":
    main()
