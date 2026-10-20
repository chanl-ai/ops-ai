# ruff: noqa: E501
# Printed lines are the experiment's record and stay whole.
"""Experiment 2: leases and a sweeper, on two real Runtime processes sharing one PostgreSQL.

Starts processes A (:8701) and B (:8702) with a 6-second lease TTL and a 1-second sweep, then:
  1. both start the dispute workflow on one thread at the same instant: one runs, the other gets 409;
  2. A runs the workflow and is killed with SIGKILL while its three extract model calls are in flight; B's sweeper
     takes the expired lease and continues the thread from its last checkpoint; the review is approved on B;
  3. prints kill-to-recovery time, model calls per process and node (the re-execution cost), and the run journal.

  OPENAI_API_KEY=... uv run python experiments/e2_leases_and_sweeper.py
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / ".logs"
EMAIL: dict[str, Any] = json.loads((ROOT / "tests" / "fixtures" / "seed" / "dispute_emails.json").read_text())[0]
TTL, SWEEP = 6, 1


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def spawn(name: str, port: int) -> tuple[subprocess.Popen[bytes], Path]:
    log = LOGS / f"e2-{name}.log"
    log.write_text("")
    env = {
        **os.environ,
        "OPS_PORT": str(port),
        "OPS_LEASE_TTL_SECONDS": str(TTL),
        "OPS_SWEEP_INTERVAL_SECONDS": str(SWEEP),
        "PYDANTIC_AI_NO_BANNER": "1",
    }
    fh = log.open("ab")
    proc = subprocess.Popen([sys.executable, "-m", "ops_agents.api"], cwd=ROOT, env=env, stdout=fh, stderr=fh)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                return proc, log
        except httpx.HTTPError:
            pass
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


def model_calls(log: Path, thread: str) -> Counter[str]:
    return Counter(m.group(1) for m in re.finditer(rf"model_call thread={thread} node=\S+ kind=(\w+)", log.read_text()))


def log_time(log: Path, event: str, thread: str) -> float | None:
    for line in log.read_text().splitlines():
        if event in line and f"thread={thread}" in line:
            return datetime.strptime(line[:23], "%Y-%m-%d %H:%M:%S,%f").timestamp()
    return None


def main() -> None:
    LOGS.mkdir(exist_ok=True)
    a, a_log = spawn("A", 8701)
    b, b_log = spawn("B", 8702)
    out(f"A pid {a.pid} on :8701, B pid {b.pid} on :8702; lease TTL {TTL}s, sweep every {SWEEP}s; shared PostgreSQL")
    api_a, api_b = (
        httpx.Client(base_url="http://127.0.0.1:8701", timeout=300),
        httpx.Client(base_url="http://127.0.0.1:8702", timeout=300),
    )
    try:
        out("\n## 1. Both processes start the same thread at the same instant")
        tid = data(api_a.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {"e2": "race"}}))[
            "threadId"
        ]
        results: dict[str, httpx.Response] = {}
        gate = threading.Barrier(2)

        def race(name: str, client: httpx.Client) -> None:
            gate.wait()
            results[name] = client.post(
                f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL, "extract_delay_ms": 1500}}
            )

        threads = [threading.Thread(target=race, args=(n, c)) for n, c in (("A", api_a), ("B", api_b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for name in ("A", "B"):
            r = results[name]
            if r.status_code == 200:
                out(f"{name}: 200, ran to end={events_of(r.text)[-1]['data']['status']}")
            else:
                out(f"{name}: {r.status_code} {json.dumps(r.json()['error'])}")

        out("\n## 2. Kill A with SIGKILL while its extract model calls are in flight")
        tid = data(api_a.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {"e2": "kill"}}))[
            "threadId"
        ]
        out(f"thread {tid}")

        def run_on_a() -> None:
            # The connection dies with the process.
            with contextlib.suppress(httpx.HTTPError):
                api_a.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAIL}})

        threading.Thread(target=run_on_a, daemon=True).start()
        deadline = time.monotonic() + 60
        while model_calls(a_log, tid)["extract"] < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        t_kill = time.time()
        os.kill(a.pid, signal.SIGKILL)
        a.wait()
        out(
            f"A killed at +0.00s with {model_calls(a_log, tid)['extract']} extract calls in flight (exit {a.returncode})"
        )

        state: dict[str, Any] = {}
        while time.time() - t_kill < 120:
            state = data(api_b.get(f"/v1/threads/{tid}/state"))
            if state["interrupt"]:
                break
            time.sleep(0.25)
        t_paused = time.time()
        t_recovery = log_time(b_log, "recovery_started", tid)
        out(
            f"B's sweeper started the recovery at +{(t_recovery or t_kill) - t_kill:.2f}s; the thread reached its review at +{t_paused - t_kill:.2f}s"
        )
        out(
            f"state on B: next={state['next']} interrupt={state['interrupt']['payload']['kind'] if state['interrupt'] else None}"
        )

        resumed = events_of(
            api_b.post(f"/v1/threads/{tid}/runs/stream", json={"resume": {"decision": "approved"}}).text
        )
        sends = sum(1 for e in resumed if e["event"] == "node_start" and e["node"] == "send_reply")
        final = data(api_b.get(f"/v1/threads/{tid}/state"))
        out(
            f"approved on B: send_reply ran {sends} time(s); status={final['values'].get('status')} sent={final['values'].get('sent')}"
        )

        out("\n## 3. Re-execution cost: model calls for this thread, by process")
        ca, cb = model_calls(a_log, tid), model_calls(b_log, tid)
        out(f"A (killed): {dict(ca)}")
        out(f"B (recovered and finished): {dict(cb)}")
        repeated = {k: min(ca[k], cb[k]) for k in ca if cb[k]}
        out(f"calls made on both processes (paid twice): {repeated} = {sum(repeated.values())} extra model call(s)")

        out("\n## 4. Run journal")
        for r in data(api_b.get(f"/v1/threads/{tid}/runs")):
            owner = (r["owner"] or "").split(":")
            out(
                f"{r['kind']:<9} {r['status']:<12} owner port {owner[1] if len(owner) > 1 else '?'}  nodes: {' → '.join(r['nodes']) or '(none recorded)'}"
            )
    finally:
        for p in (a, b):
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)


if __name__ == "__main__":
    main()
