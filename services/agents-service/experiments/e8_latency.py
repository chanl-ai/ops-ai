# ruff: noqa: E501
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false
# Printed lines are the experiment's record and stay whole; asyncpg and parts of Pydantic AI are untyped.
"""Experiment E8: chat turn latency, and how much of it is ours rather than the model's.

  uv run python experiments/e8_latency.py                                          # stored + fake parts, no tokens
  OPENAI_API_KEY=... uv run python experiments/e8_latency.py --only timed                    # 9 real model calls

Project rule: at most 10 real model calls per experiment unless the owner approves more; everything else runs on
the fake model port. The timed part stops itself at 10 calls; the live part needs --live-approved.

Parts:
  stored   server-side durations of the live turns already run (from the stored messages, no new calls)
  live     (needs --live-approved) 200 chat turns against the running agents-service on :8700 (real model): 50 plain at concurrency 1,
           50 plain at concurrency 5, 50 with a read tool, 50 with a write tool up to its approval.
  timed    8 turns (9 model calls) in-process with the real model wrapped in a timer: each turn's model time and
           tokens, so overhead = total - model time.
  fake     plain, read-tool and write-tool turns, concurrency 1 and 5, in-process with an instant scripted model:
           the total is our overhead, exactly.
  workflow 20 runs of the simple workflow in-process through the four calls, fake model ports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LIVE = os.environ.get("E8_BASE", "http://127.0.0.1:8700")
DB = "ops_e8"
URL = f"postgresql+asyncpg://ops:ops@localhost:5477/{DB}"

PLAIN = [
    ("ag_fraud", "What is the daily wire limit for a personal account?"),
    ("ag_fraud", "What is our new-payee wire hold rule?"),
    ("ag_fraud", "Who can release a wire hold early when the risk score is 75?"),
    ("ag_fraud", "How long do we keep customer due diligence records?"),
    ("ag_branch", "What is the wire cut-off time at the Halifax branch?"),
    ("ag_branch", "What is the refund window for an annual card fee?"),
    ("ag_dispute", "When do we owe a provisional credit on a card dispute?"),
]
READ = ("ag_fraud", "Look up account CHQ-2219 and tell me its daily wire limit.")
WRITE = ("ag_fraud", "Place a 24-hour hold on wire W-88213, the payee was added this morning.")
KBS = {"ag_fraud": ["kb_people", "kb_eng"], "ag_branch": ["kb_support"], "ag_dispute": ["kb_legal"]}


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


@dataclass
class Turn:
    group: str
    ttfb: float = 0.0
    first_text: float | None = None
    total: float = 0.0
    model: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    ok: bool = True
    events: list[str] = field(default_factory=list[str])


def pct(values: list[float], q: int) -> float:
    if not values:
        return float("nan")
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[q - 1]


def row(label: str, turns: list[Turn], *, model: bool = False) -> str:
    ok = [t for t in turns if t.ok]
    cells = [f"{label} (n={len(ok)}{'' if len(ok) == len(turns) else f', {len(turns) - len(ok)} failed'})"]
    for values in ([t.ttfb for t in ok], [t.first_text for t in ok if t.first_text is not None], [t.total for t in ok]):
        cells.append(" / ".join(f"{pct(values, q) * 1000:.0f}" for q in (50, 95, 99)))
    if model:
        cells.append(" / ".join(f"{pct([t.model or 0.0 for t in ok], q) * 1000:.0f}" for q in (50, 95, 99)))
        cells.append(" / ".join(f"{pct([t.total - (t.model or 0.0) for t in ok], q) * 1000:.0f}" for q in (50, 95, 99)))
    return "| " + " | ".join(cells) + " |"


async def stream_turn(client: httpx.AsyncClient, group: str, agent: str, text: str) -> Turn:
    """One chat turn exactly as the console makes it: create the thread, then time the streamed reply."""
    turn = Turn(group)
    try:
        r = await client.post("/chat/threads", json={"agentId": agent, "kbIds": KBS[agent]})
        tid = r.json()["data"]["id"]
        started = time.perf_counter()
        async with client.stream(
            "POST", f"/chat/threads/{tid}/messages", json={"content": text}, headers={"Accept": "text/event-stream"}
        ) as res:
            buf = ""
            async for chunk in res.aiter_text():
                now = time.perf_counter() - started
                if not turn.ttfb:
                    turn.ttfb = now
                buf += chunk
                *frames, buf = buf.split("\n\n")
                for frame in frames:
                    payload = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
                    if not payload:
                        continue
                    kind = json.loads(payload)["type"]
                    turn.events.append(kind)
                    if kind == "text" and turn.first_text is None:
                        turn.first_text = now
                    if kind == "error":
                        turn.ok = False
        turn.total = time.perf_counter() - started
    except (httpx.HTTPError, KeyError):
        turn.ok = False
    return turn


async def run_group(
    client: httpx.AsyncClient, group: str, prompts: list[tuple[str, str]], concurrency: int, before: Any = None
) -> list[Turn]:
    sem = asyncio.Semaphore(concurrency)

    async def one(agent: str, text: str) -> Turn:
        async with sem:
            if before:
                before()
            t = await stream_turn(client, group, agent, text)
            if before:
                t.model, t.tokens_in, t.tokens_out = TIMED.take()
            return t

    return list(await asyncio.gather(*(one(a, q) for a, q in prompts)))


def plain(n: int) -> list[tuple[str, str]]:
    return [PLAIN[i % len(PLAIN)] for i in range(n)]


# ── the timed model ──


class Timer:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.seconds, self.tokens_in, self.tokens_out = 0.0, 0, 0

    def take(self) -> tuple[float, int, int]:
        got = (self.seconds, self.tokens_in, self.tokens_out)
        self.reset()
        return got


TIMED = Timer()
CALL_CAP = 10  # per-experiment cap on real model calls
CALLS = [0]


class TimedModel(WrapperModel):
    """Times every streamed model request (connection, generation and transfer) and adds up its token usage."""

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[Any],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        CALLS[0] += 1
        if CALLS[0] > CALL_CAP:
            raise RuntimeError(f"real model call cap of {CALL_CAP} reached; stopping")
        started = time.perf_counter()
        async with self.wrapped.request_stream(messages, model_settings, model_request_parameters, run_context) as rs:
            yield rs
        TIMED.seconds += time.perf_counter() - started
        usage = rs.usage
        TIMED.tokens_in += usage.input_tokens or 0
        TIMED.tokens_out += usage.output_tokens or 0


async def scratch_db() -> None:
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


@asynccontextmanager
async def in_process(model: Model) -> AsyncGenerator[httpx.AsyncClient]:
    """The real app, in this process, on the scratch database, with the given model."""
    from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415

    from ops_agents.api.app import create_app  # noqa: PLC0415
    from ops_service_kit.settings import Settings  # noqa: PLC0415

    app = create_app(Settings(database_url=URL), model=model, checkpointer=InMemorySaver())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://e8", timeout=300) as c,
    ):
        yield c


async def workflow_runs(client: httpx.AsyncClient, n: int) -> list[Turn]:
    turns: list[Turn] = []
    for i in range(n):
        t = Turn("workflow")
        question = PLAIN[i % 4][1]  # the four fraud-and-compliance questions, answered from every knowledge base
        tid = (await client.post("/v1/threads", json={"graph": "simple_workflow", "metadata": {"e8": i}})).json()[
            "data"
        ]["threadId"]
        started = time.perf_counter()
        async with client.stream(
            "POST", f"/v1/threads/{tid}/runs/stream", json={"input": {"question": question}}
        ) as res:
            buf = ""
            async for chunk in res.aiter_text():
                now = time.perf_counter() - started
                if not t.ttfb:
                    t.ttfb = now
                buf += chunk
                *frames, buf = buf.split("\n\n")
                for frame in frames:
                    payload = "".join(line[5:].strip() for line in frame.split("\n") if line.startswith("data:"))
                    if payload:
                        e = json.loads(payload)
                        t.events.append(e["event"])
                        if e["event"] == "text" and t.first_text is None:
                            t.first_text = now
                        if e["event"] == "error":
                            t.ok = False
        t.total = time.perf_counter() - started
        turns.append(t)
    return turns


async def stored_live(since_minutes: int) -> dict[str, list[float]]:
    """Server-side duration of each live turn already run on :8700: the assistant message's time (set when the turn
    finished) minus the user message's time (set when it started). No first-byte or first-text times: those were
    measured by the client and lost when the run was stopped."""
    conn = await asyncpg.connect("postgresql://ops:ops@localhost:5477/ops_runtime")
    rows = await conn.fetch(
        """
        SELECT t.title, u.at AS started, a.at AS finished
          FROM messages a JOIN threads t ON t.id = a.thread_id
          JOIN messages u ON u.thread_id = a.thread_id AND u.role = 'user'
         WHERE a.role = 'assistant' AND a.content <> ''
           AND a.at > to_char(now() at time zone 'utc' - make_interval(mins => $1), 'YYYY-MM-DD"T"HH24:MI:SS')
         ORDER BY u.at
        """,
        since_minutes,
    )
    await conn.close()

    def secs(r: Any) -> float:
        from datetime import datetime  # noqa: PLC0415

        f = "%Y-%m-%dT%H:%M:%S.%fZ"
        return (datetime.strptime(r["finished"], f) - datetime.strptime(r["started"], f)).total_seconds()

    read = [secs(r) for r in rows if r["title"].startswith("Look up account")]
    plain_rows = [r for r in rows if not r["title"].startswith("Look up account")]
    return {
        "cold (first turn)": [secs(r) for r in plain_rows[:1]],
        "plain, concurrency 1": [secs(r) for r in plain_rows[1:51]],
        "plain, concurrency 5": [secs(r) for r in plain_rows[51:101]],
        "read tool (lookup_account), stopped at 17 of 50": read,
    }


HEADER = "| Group | First byte ms p50 / p95 / p99 | First text ms p50 / p95 / p99 | Total ms p50 / p95 / p99 |"
HEADER_MODEL = HEADER + " Model ms p50 / p95 / p99 | Overhead (total - model) ms p50 / p95 / p99 |"


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["stored", "live", "timed", "fake", "workflow"], action="append")
    ap.add_argument(
        "--live-approved",
        action="store_true",
        help="the live part makes ~250 real model calls; the owner approves first",
    )
    ap.add_argument("--since-minutes", type=int, default=120, help="window for the stored part")
    args = ap.parse_args()
    parts = set(args.only or ["stored", "fake", "workflow"])

    if "stored" in parts:
        out("## Stored: server-side duration of the live turns already run on :8700 (no new model calls)")
        groups = await stored_live(args.since_minutes)
        out("| Group | Turns | Server-side total ms p50 / p95 / p99 |")
        out("|---|---|---|")
        for label, values in groups.items():
            out(f"| {label} | {len(values)} | {' / '.join(f'{pct(values, q) * 1000:.0f}' for q in (50, 95, 99))} |")

    if "live" in parts:
        if not args.live_approved:
            raise SystemExit(
                "the live part makes ~250 real model calls; pass --live-approved once the owner has approved it"
            )
        out(f"## Live: chat turns against {LIVE}")
        async with httpx.AsyncClient(base_url=LIVE, timeout=300) as c:
            live = {
                "plain, concurrency 1": await run_group(c, "plain c1", plain(50), 1),
                "plain, concurrency 5": await run_group(c, "plain c5", plain(50), 5),
                "read tool": await run_group(c, "read", [READ] * 50, 1),
                "write tool to its approval": await run_group(c, "write", [WRITE] * 50, 1),
            }
        out(HEADER)
        out("|---|---|---|---|")
        for label, turns in live.items():
            out(row(label, turns))

    if parts & {"timed", "fake", "workflow"}:
        await scratch_db()

    if "timed" in parts:
        from ops_agent_kernel.models import build_model  # noqa: PLC0415
        from ops_service_kit.settings import Settings  # noqa: PLC0415

        out(f"\n## Timed: 8 turns in-process, real model wrapped in a timer (cap {CALL_CAP} model calls)")
        async with in_process(TimedModel(build_model(Settings()))) as c:
            timed = {
                "plain (first is cold)": await run_group(c, "plain", plain(5), 1, before=lambda: None),
                "read tool (2 model calls)": await run_group(c, "read", [READ], 1, before=lambda: None),
                "write tool to its approval": await run_group(c, "write", [WRITE] * 2, 1, before=lambda: None),
            }
        out(HEADER_MODEL)
        out("|---|---|---|---|---|---|")
        for label, turns in timed.items():
            out(row(label, turns, model=True))
        all_timed = [t for ts in timed.values() for t in ts]
        tin, tout = sum(t.tokens_in for t in all_timed), sum(t.tokens_out for t in all_timed)
        out(f"real model calls: {CALLS[0]}; tokens: {tin} in, {tout} out over {len(all_timed)} turns")
        p_in = sum(t.tokens_in for t in timed["plain (first is cold)"]) / 5
        p_out = sum(t.tokens_out for t in timed["plain (first is cold)"]) / 5
        r_in, r_out = timed["read tool (2 model calls)"][0].tokens_in, timed["read tool (2 model calls)"][0].tokens_out
        out(f"per turn: plain {p_in:.0f} in / {p_out:.0f} out; read {r_in} in / {r_out} out")
        out(
            f"estimate for the 118 live turns run earlier (101 plain, 17 read): {101 * p_in + 17 * r_in:.0f} in, {101 * p_out + 17 * r_out:.0f} out"
        )

    if "fake" in parts:
        from tests.conftest import scripted_model  # noqa: PLC0415

        out("\n## Fake model: in-process with an instant scripted model (total = our overhead)")
        async with in_process(scripted_model()) as c:
            await stream_turn(c, "warm-up", *PLAIN[0])
            fake = {
                "plain, concurrency 1": await run_group(c, "fake", plain(50), 1),
                "plain, concurrency 5": await run_group(c, "fake c5", plain(50), 5),
                "read tool, concurrency 1": await run_group(
                    c, "fake read", [("ag_fraud", "Look up account CHQ-2219")] * 50, 1
                ),
                "write tool to its approval": await run_group(c, "fake write", [WRITE] * 50, 1),
            }
        out(HEADER)
        out("|---|---|---|---|")
        for label, turns in fake.items():
            out(row(label, turns))
        w = fake["write tool to its approval"]
        out(
            f"fake write turns that ended at an approval widget: {sum(1 for t in w if 'widget' in t.events)}/{len(w)}; fake read turns that called the tool: {sum(1 for t in fake['read tool, concurrency 1'] if 'tool_start' in t.events)}/50"
        )

    if "workflow" in parts:
        from tests.conftest import FakeGraphModels, scripted_model  # noqa: PLC0415

        out("\n## Simple workflow in-process through the four calls, fake model ports, 20 runs")
        from langgraph.checkpoint.memory import InMemorySaver  # noqa: PLC0415

        from ops_agents.api.app import create_app  # noqa: PLC0415
        from ops_service_kit.settings import Settings  # noqa: PLC0415

        app = create_app(
            Settings(database_url=URL),
            model=scripted_model(),
            checkpointer=InMemorySaver(),
            graph_models=FakeGraphModels(),
        )
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://e8", timeout=300) as c,
        ):
            await workflow_runs(c, 1)
            wf = await workflow_runs(c, 20)
        out(HEADER)
        out("|---|---|---|---|")
        out(row("simple_workflow, fake ports", wf))


if __name__ == "__main__":
    asyncio.run(main())
