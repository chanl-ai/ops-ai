# ruff: noqa: E501
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false, reportOptionalSubscript=false
# Printed lines are the experiment's record and stay whole; asyncpg records and LangGraph graphs are partly untyped.
"""Experiment E2b: lease generations as fencing tokens, on real processes and a scratch database.

  OPENAI_API_KEY=... uv run python experiments/e2b_fencing.py            # proof + cost
  uv run python experiments/e2b_fencing.py --only cost                                         # cost only, no tokens

Proof: a gateway (:8721) and two Runtimes A (:8701) and B (:8702) share the scratch database `ops_e2b`. A starts the
dispute workflow and is frozen with SIGSTOP mid-extract; B's sweeper takes the lease over (generation + 1), runs the
thread to its review, and the reply is approved and sent through the gateway. A is thawed with SIGCONT: its checkpoint
write and a gateway write with its old generation must both be refused, and the reply must have been sent once.

Cost: E4's references scenario with and without the fence on every checkpoint write.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import asyncpg
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOGS = ROOT / ".logs"
DB = "ops_e2b"
URL = f"postgresql+asyncpg://ops:ops@localhost:5477/{DB}"
# The team the experiment's threads are written under; the Runtime writes each run under its thread's team.
E2B_TEAM = "local"
DSN = f"postgresql://ops:ops@localhost:5477/{DB}"
EMAIL: dict[str, Any] = json.loads((ROOT / "tests" / "fixtures" / "seed" / "dispute_emails.json").read_text())[1]
TTL, SWEEP = 4, 1


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


async def scratch() -> None:
    admin = await asyncpg.connect("postgresql://ops:ops@localhost:5477/ops_runtime")
    await admin.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {DB}")
    await admin.close()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        env={**os.environ, "OPS_DATABASE_URL": URL},
    )


def spawn(name: str, module: str, port: int, extra: dict[str, str]) -> tuple[subprocess.Popen[bytes], Path]:
    log = LOGS / f"e2b-{name}.log"
    log.write_text("")
    env = {**os.environ, "OPS_DATABASE_URL": URL, "PYDANTIC_AI_NO_BANNER": "1", **extra}
    fh = log.open("ab")
    proc = subprocess.Popen([sys.executable, "-m", module], cwd=ROOT, env=env, stdout=fh, stderr=fh)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc, log
        time.sleep(0.3)
    raise SystemExit(f"{name} did not start; see {log}")


def data(res: httpx.Response) -> Any:
    body = res.json()
    if not body.get("success"):
        raise SystemExit(f"{res.request.method} {res.request.url.path} -> {res.status_code} {body}")
    return body["data"]


def events_of(text: str) -> list[dict[str, Any]]:
    evs: list[dict[str, Any]] = []
    for frame in text.split("\n\n"):
        payload = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
        if payload:
            evs.append(json.loads(payload))
    return evs


async def lease_row(thread: str) -> dict[str, Any]:
    conn = await asyncpg.connect(DSN)
    row = await conn.fetchrow(
        "SELECT owner, run_id, generation, released_at FROM thread_leases WHERE thread_id = $1", thread
    )
    await conn.close()
    return dict(row) if row else {}


async def checkpoints(thread: str) -> int:
    conn = await asyncpg.connect(DSN)
    n = await conn.fetchval("SELECT count(*) FROM ops_checkpoints WHERE thread_id = $1", thread)
    await conn.close()
    return int(n)


async def late_checkpoint(thread: str, generation: int) -> str:
    """The checkpoint write a stalled A would make on waking, through the same saver the Runtime uses."""
    from langgraph.checkpoint.base import empty_checkpoint  # noqa: PLC0415

    from ops_agents.graphs.checkpointer import LOCAL_TENANT  # noqa: PLC0415
    from ops_checkpointer import LeaseSupersededError, open_saver  # noqa: PLC0415

    async with open_saver(URL, tenant_id=LOCAL_TENANT, team_id=E2B_TEAM) as saver:
        cfg: Any = {"configurable": {"thread_id": thread, "checkpoint_ns": "", "lease_generation": generation}}
        try:
            await saver.aput(cfg, empty_checkpoint(), {"source": "loop", "step": 99, "parents": {}}, {})
        except LeaseSupersededError as e:
            return f"refused: {e}"
    return "ACCEPTED"


async def sent_step_of(thread: str) -> str:
    conn = await asyncpg.connect(DSN)
    step = await conn.fetchval(
        "SELECT step FROM gateway_calls WHERE thread_id = $1 AND tool = 'send_reply' AND effect", thread
    )
    await conn.close()
    return str(step)


async def sends(thread: str) -> list[dict[str, Any]]:
    conn = await asyncpg.connect(DSN)
    rows = await conn.fetch(
        "SELECT decision, outcome, effect, reasons FROM gateway_calls WHERE thread_id = $1 AND tool = 'send_reply' ORDER BY created_at",
        thread,
    )
    await conn.close()
    return [dict(r) for r in rows]


def proof() -> None:
    LOGS.mkdir(exist_ok=True)
    asyncio.run(scratch())
    gw, _ = spawn("gateway", "ops_tools", 8721, {"OPS_GATEWAY_PORT": "8721"})
    common = {
        "OPS_GATEWAY_URL": "http://127.0.0.1:8721",
        "OPS_LEASE_TTL_SECONDS": str(TTL),
        "OPS_SWEEP_INTERVAL_SECONDS": str(SWEEP),
    }
    a, a_log = spawn("A", "ops_agents.api", 8701, {**common, "OPS_PORT": "8701"})
    b, _ = spawn("B", "ops_agents.api", 8702, {**common, "OPS_PORT": "8702"})
    out(f"gateway :8721, A pid {a.pid} :8701, B pid {b.pid} :8702; TTL {TTL}s, sweep {SWEEP}s; scratch database {DB}")
    api_a = httpx.Client(base_url="http://127.0.0.1:8701", timeout=300)
    api_b = httpx.Client(base_url="http://127.0.0.1:8702", timeout=300)
    result_a: dict[str, Any] = {}
    try:
        tid = data(api_a.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {"e2b": "fence"}}))[
            "threadId"
        ]
        out(f"\n## 1. A starts the dispute workflow on {tid}; extracts hold 6 s each")

        def run_on_a() -> None:
            with contextlib.suppress(httpx.HTTPError):
                r = api_a.post(
                    f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL, "extract_delay_ms": 6000}}
                )
                result_a["events"] = events_of(r.text)

        ta = threading.Thread(target=run_on_a, daemon=True)
        ta.start()
        deadline = time.monotonic() + 60
        while asyncio.run(checkpoints(tid)) < 3 and time.monotonic() < deadline:
            time.sleep(0.1)  # input, before-classify and after-classify checkpoints: A is inside the extract delay
        before = asyncio.run(lease_row(tid))
        os.kill(a.pid, signal.SIGSTOP)
        t_stop = time.time()
        out(
            f"A frozen with SIGSTOP mid-extract; lease owner port {before['owner'].split(':')[1]} generation {before['generation']}"
        )

        out("\n## 2. B's sweeper takes the lease over and runs the thread to its review")
        state: dict[str, Any] = {}
        while time.time() - t_stop < 120:
            state = data(api_b.get(f"/v1/threads/{tid}/state"))
            if state["interrupt"]:
                break
            time.sleep(0.5)
        taken = asyncio.run(lease_row(tid))
        out(
            f"lease now: owner port {taken['owner'].split(':')[1]} generation {taken['generation']} (released={taken['released_at'] is not None}); thread waiting at {state['next']} after {time.time() - t_stop:.1f}s"
        )
        approval = data(api_b.post(f"/v1/threads/{tid}/approvals", json={}))
        resumed = events_of(
            api_b.post(
                f"/v1/threads/{tid}/runs/stream",
                json={"resume": {"decision": "approved", "approvalToken": approval["approvalToken"]}},
            ).text
        )
        out(
            f"approved on B: send_reply ran {sum(1 for e in resumed if e['event'] == 'node_start' and e['node'] == 'send_reply')} time(s); end={resumed[-1]['data']}"
        )

        out("\n## 3. A thawed with SIGCONT: its writes carry the old generation")
        os.kill(a.pid, signal.SIGCONT)
        ta.join(timeout=60)
        evs = result_a.get("events", [])
        err = next((e["data"]["message"] for e in evs if e["event"] == "error"), None)
        out(f"A's run ended: {evs[-1]['event'] if evs else 'no events'}; error: {err}")
        calls_a = [
            line.split("kind=")[1] for line in a_log.read_text().splitlines() if f"model_call thread={tid}" in line
        ]
        out(f"A's model calls over its whole run: {calls_a}")
        # A's realistic late write is the same approved send B made (same step, same input), which OPA allows:
        # only the fence can refuse it. The input is rebuilt from the state the send was made from.
        sent_step, values = asyncio.run(sent_step_of(tid)), data(api_b.get(f"/v1/threads/{tid}/state"))["values"]
        late = httpx.post(
            "http://127.0.0.1:8721/v1/calls",
            headers={"X-Lease-Generation": str(before["generation"])},
            json={
                "tool": "send_reply",
                "input": {"to": EMAIL["sender"], "subject": f"Re: {EMAIL['subject']}", "body": values["draft"]},
                "key": sent_step,
                "runContext": {"thread": tid, "step": sent_step, "sub": "runtime:local", "act": "graph"},
                "approvalToken": approval["approvalToken"],
            },
            timeout=10,
        )
        out(
            f"A's late gateway write with generation {before['generation']}: {late.status_code} {late.json()['error']['details']['reasons'] if late.status_code != 200 else late.json()['data']}"
        )
        out(
            f"A's late checkpoint write with generation {before['generation']}: {asyncio.run(late_checkpoint(tid, before['generation']))}"
        )

        out("\n## 4. What stands")
        final = data(api_b.get(f"/v1/threads/{tid}/state"))
        sent = asyncio.run(sends(tid))
        effects = [s for s in sent if s["effect"]]
        out(
            f"thread status={final['values'].get('status')} sent={final['values'].get('sent')}; send_reply calls at the gateway: {[(s['decision'], s['outcome']) for s in sent]}; with an effect: {len(effects)}"
        )
        for r in data(api_b.get(f"/v1/threads/{tid}/runs")):
            crashed = (
                f"; crashed while running {r['crashed']['running']} (owner port {(r['crashed']['owner'] or '?').split(':')[1]}, generation {r['crashed']['generation']})"
                if r.get("crashed")
                else ""
            )
            out(
                f"  run {r['kind']:<9} {r['status']:<12} owner {(r['owner'] or '?:?').split(':')[1]} nodes {' → '.join(r['nodes']) or '-'}{crashed}"
            )
    finally:
        for p in (a, b, gw):
            with contextlib.suppress(ProcessLookupError):
                os.kill(p.pid, signal.SIGCONT)
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)


async def cost(cases: int) -> None:
    from langgraph.types import Command  # noqa: PLC0415

    import experiments.e4_checkpoint_growth as e4  # noqa: PLC0415 - reuse E4's harness and its scratch database
    from ops_agents.graphs.registry import build_graphs  # noqa: PLC0415
    from ops_checkpointer import open_saver  # noqa: PLC0415

    await e4.scratch_db()
    out(f"\n## 5. Cost: E4's references scenario, {cases} cases, checkpoint writes with and without the fence")
    rows: list[tuple[str, float, float]] = []
    async with open_saver(e4.SCRATCH, tenant_id="e2b", team_id="e2b", max_size=8) as saver:
        e4.instrument(saver)
        for label, fenced in (("unfenced", False), ("fenced", True), ("unfenced again", False), ("fenced again", True)):
            files: dict[str, str] = {}
            t = e4.CURRENT[0] = e4.Timings()
            graph = build_graphs(e4.deps(files), saver)["complex_workflow"]
            for i in range(cases):
                thread = f"cost_{label.replace(' ', '_')}_{i:03d}"
                configurable: dict[str, Any] = {"thread_id": thread}
                if fenced:
                    configurable["lease_generation"] = 1
                    await saver.araise_fence(thread, 1)
                cfg: Any = {"configurable": configurable, "max_concurrency": 4}
                await graph.ainvoke({"email": e4.make_email(i, 20, 2048, files)}, cfg)
                await graph.ainvoke(Command(resume={"decision": "approved"}), cfg)
            puts = [x[0] for x in t.puts]
            writes = [x[0] for x in t.writes]
            rows.append((label, e4.pct(puts, 50), e4.pct(puts, 95)))
            out(
                f"{label}: checkpoint write p50 {e4.pct(puts, 50):.2f} ms p95 {e4.pct(puts, 95):.2f} ms; task writes p95 {e4.pct(writes, 95):.2f} ms ({len(puts)} checkpoints)"
            )
    unf = [r for r in rows if r[0].startswith("unfenced")]
    fen = [r for r in rows if r[0].startswith("fenced")]
    out(
        f"fence cost at p95: {sum(r[2] for r in fen) / len(fen) - sum(r[2] for r in unf) / len(unf):+.2f} ms; at p50: {sum(r[1] for r in fen) / len(fen) - sum(r[1] for r in unf) / len(unf):+.2f} ms"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["proof", "cost"], action="append")
    ap.add_argument("--cases", type=int, default=50)
    args = ap.parse_args()
    parts = set(args.only or ["proof", "cost"])
    if "proof" in parts:
        proof()
    if "cost" in parts:
        asyncio.run(cost(args.cases))


if __name__ == "__main__":
    main()
