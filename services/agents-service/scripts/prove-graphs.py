"""Proves chat, a simple workflow and a complex workflow run on one runtime through the same four calls.

Every graph goes through `drive(graph, input, resume_fn)`: create a thread, stream a run with the input, resume each
interrupt with `resume_fn`, read the state. The HTTP calls each graph made are printed and compared.

Then the restart proof: a second Runtime process is started on a spare port, the dispute workflow runs to its review
interrupt, the process is killed with SIGKILL, a new process starts, and the run resumes and finishes.

Run with the model key in the environment (from .env or your secrets manager):
  uv run python scripts/prove-graphs.py
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("PROVE_BASE", "http://127.0.0.1:8700")
RESTART_PORT = 8701
EMAILS: list[dict[str, Any]] = json.loads((ROOT / "tests" / "fixtures" / "seed" / "dispute_emails.json").read_text())


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


@dataclass
class Trace:
    calls: list[str] = field(default_factory=list[str])
    nodes: list[str] = field(default_factory=list[str])
    interrupts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    text: str = ""
    sent: int = 0


def data(res: httpx.Response) -> Any:
    body = res.json()
    if not body.get("success"):
        raise SystemExit(f"{res.request.method} {res.request.url.path} -> {res.status_code} {body}")
    return body["data"]


def stream(client: httpx.Client, trace: Trace, tid: str, body: dict[str, Any]) -> str:
    """Streams one run; returns its end status."""
    trace.calls.append("POST /v1/threads/{id}/runs/stream")
    status = "?"
    with client.stream("POST", f"/v1/threads/{tid}/runs/stream", json=body) as res:
        if res.status_code != 200:
            res.read()
            raise SystemExit(f"runs/stream -> {res.status_code} {res.text}")
        buf = ""
        for chunk in res.iter_text():
            buf += chunk
            *frames, buf = buf.split("\n\n")
            for frame in frames:
                payload = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
                if not payload:
                    continue
                e = json.loads(payload)
                kind = e["event"]
                if kind == "node_start":
                    trace.nodes.append(e["node"])
                    trace.sent += e["node"] == "send_reply"
                elif kind == "text":
                    trace.text += e["data"]
                elif kind == "interrupt":
                    trace.interrupts.append(e["data"]["payload"])
                elif kind == "error":
                    raise SystemExit(f"run error: {e['data']['message']}")
                elif kind == "end":
                    status = e["data"]["status"]
    return status


def drive(
    client: httpx.Client, graph: str, graph_input: dict[str, Any], resume_fn: Callable[[dict[str, Any]], dict[str, Any]]
) -> tuple[Trace, dict[str, Any]]:
    """The one code path every graph runs through."""
    trace = Trace()
    trace.calls.append("POST /v1/threads")
    tid = data(client.post("/v1/threads", json={"graph": graph, "metadata": {"source": "prove-graphs"}}))["threadId"]
    status = stream(client, trace, tid, {"input": graph_input})
    while status == "interrupted":
        status = stream(client, trace, tid, {"resume": resume_fn(trace.interrupts[-1])})
    trace.calls.append("GET /v1/threads/{id}/state")
    state = data(client.get(f"/v1/threads/{tid}/state"))
    return trace, state


def approve(payload: dict[str, Any]) -> dict[str, Any]:
    # A money movement needs a step-up from the console; any non-empty token stands in for it here.
    return (
        {"decision": "approved", "stepUpToken": "stepup_prove_graphs"}
        if payload.get("step_up")
        else {"decision": "approved"}
    )


def collapse(nodes: list[str]) -> str:
    out_: list[str] = []
    for n in nodes:
        if out_ and out_[-1].split(" x")[0] == n:
            head, _, count = out_[-1].partition(" x")
            out_[-1] = f"{head} x{int(count or 1) + 1}"
        else:
            out_.append(n)
    return " → ".join(out_)


def report(name: str, trace: Trace, extra: list[str]) -> None:
    out(f"\n=== {name}")
    out("calls:")
    for c in trace.calls:
        out(f"  {c}")
    out(f"nodes: {collapse(trace.nodes)}")
    for p in trace.interrupts:
        shown = {
            k: v for k, v in p.items() if k in ("kind", "review_id", "tool", "action", "step_up", "score", "attempts")
        }
        out(f"interrupt: {json.dumps(shown)}")
    for line in extra:
        out(line)


def wait_up(url: str, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise SystemExit(f"{url} did not come up")


def spawn() -> subprocess.Popen[bytes]:
    env = {**os.environ, "OPS_PORT": str(RESTART_PORT), "PYDANTIC_AI_NO_BANNER": "1"}
    log = (ROOT / ".logs" / "restart-proof.log").open("ab")
    proc = subprocess.Popen([sys.executable, "-m", "ops_agents.api"], cwd=ROOT, env=env, stdout=log, stderr=log)
    wait_up(f"http://127.0.0.1:{RESTART_PORT}")
    return proc


def pending_kind(state: dict[str, Any]) -> str | None:
    pending: dict[str, Any] | None = state.get("interrupt")
    return pending["payload"].get("kind") if pending else None


def restart_proof() -> None:
    url = f"http://127.0.0.1:{RESTART_PORT}"
    out(f"\n=== restart: complex_workflow on a second process at {url}")
    proc = spawn()
    out(f"started pid {proc.pid}")
    with httpx.Client(base_url=url, timeout=300) as client:
        trace = Trace()
        tid = data(
            client.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {"source": "restart-proof"}})
        )["threadId"]
        status = stream(client, trace, tid, {"input": {"email": EMAILS[1]}})
        shown = trace.interrupts[-1]["review_id"]
        out(f"run 1 ended {status} at nodes: {collapse(trace.nodes)}; review id shown: {shown}")
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait()
    out(f"killed pid {proc.pid} with SIGKILL (exit {proc.returncode})")
    proc = spawn()
    out(f"started pid {proc.pid}")
    try:
        with httpx.Client(base_url=url, timeout=300) as client:
            state = data(client.get(f"/v1/threads/{tid}/state"))
            out(f"state after restart: next={state['next']} interrupt={pending_kind(state)}")
            trace2 = Trace()
            status = stream(client, trace2, tid, {"resume": {"decision": "approved"}})
            final = data(client.get(f"/v1/threads/{tid}/state"))
            out(
                f"resumed: {collapse(trace2.nodes)}; ended {status};"
                f" status={final['values'].get('status')} sent={final['values'].get('sent')}"
                f" review id after resume: {final['values'].get('review_id')}"
            )
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run chat, a simple workflow and a complex workflow through the same four calls,"
        " then a kill-and-resume.",
        epilog="Run with the model key in the environment (.env or your secrets manager)"
        " uv run python scripts/prove-graphs.py --only complex",
    )
    parser.add_argument(
        "--only",
        choices=["agent", "simple", "complex", "restart"],
        action="append",
        help="Run one part (repeatable). agent: chat agent with an approval. simple: product question with a citation."
        " complex: dispute email with fan-out, grade loop and review. restart: kill the API at the review and resume."
        " Default: all four.",
    )
    parser.add_argument("--base", default=BASE, help=f"Runtime URL for agent, simple and complex (default {BASE})")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parts = set(args.only or ["agent", "simple", "complex", "restart"])
    traces: dict[str, Trace] = {}
    with httpx.Client(base_url=args.base, timeout=300) as client:
        if "agent" in parts:
            agent, agent_state = drive(
                client,
                "agent_wrapper",
                {
                    "agent_id": "ag_fraud",
                    "message": "Place a 24-hour hold on wire W-88213, the payee was added this morning.",
                },
                approve,
            )
            report("agent_wrapper (chat agent)", agent, [f"final: {agent_state['values'].get('reply')}"])
            traces["agent_wrapper"] = agent
        if "simple" in parts:
            simple, simple_state = drive(
                client, "simple_workflow", {"question": "What is the daily wire limit for a personal account?"}, approve
            )
            cites = "; ".join(
                f"[{c['n']}] {c['title']} — {c['section']}" for c in simple_state["values"].get("citations", [])
            )
            report(
                "simple_workflow (reply to a product question)",
                simple,
                [f"answer: {simple_state['values'].get('answer')}", f"citations: {cites or 'none'}"],
            )
            traces["simple_workflow"] = simple
        if "complex" in parts:
            complex_, complex_state = drive(
                client, "complex_workflow", {"email": EMAILS[0], "grade_overrides": [0.4]}, approve
            )
            v = complex_state["values"]
            report(
                "complex_workflow (dispute email)",
                complex_,
                [
                    f"extracted: {[x['name'] for x in v.get('extractions', [])]}",
                    f"attempts: {v.get('attempts')} final score: {v.get('score')}",
                    f"send_reply ran: {complex_.sent} time(s); sent={v.get('sent')} status={v.get('status')}",
                ],
            )
            traces["complex_workflow"] = complex_
        if len(traces) > 1:
            same = len({frozenset(t.calls) for t in traces.values()}) == 1
            out(f"\nSame endpoints for all graphs run, through the one drive() function: {same}")
            for name, t in traces.items():
                out(f"  {name}: {len(t.calls)} calls, {len(t.interrupts)} resume(s)")
    if "restart" in parts:
        restart_proof()


if __name__ == "__main__":
    main()
