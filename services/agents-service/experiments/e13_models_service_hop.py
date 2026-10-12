# ruff: noqa: E501
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportMissingTypeStubs=false
# Printed lines are the experiment's record and stay whole; asyncpg is untyped.
"""Experiment E13: what the models-service hop adds to a chat turn (c-009), against E8's direct numbers.

  uv run python experiments/e13_models_service_hop.py                                  # scripted parts, no tokens
  OPENAI_API_KEY=... uv run python experiments/e13_models_service_hop.py --only real --real-approved   # 10 real calls

Project rule: at most 10 real model calls per experiment unless the owner approves more. The real part makes five
plain turns direct and five through models-service on one openai-compatible alias, and stops itself at 10 calls.

Parts:
  scripted  kernel turns with an instant scripted model: in process (no hop) against through a real models-service
            server on its scripted provider (one HTTP round trip, key lookup, rate count, log row and spend), at
            concurrency 1 and 5. The difference is the hop, exactly.
  real      (needs OPENAI_API_KEY and --real-approved) the same plain turn E8 timed, five direct and five through
            models-service on an openai-compatible alias pointed at the provider.
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
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from ops_agent_kernel.events import TurnFinished
from ops_agent_kernel.kernel import run_turn
from ops_agent_kernel.models import ModelsServiceModels
from ops_agent_kernel.ports import KernelPorts, ToolOutcome
from ops_agent_kernel.types import AgentSettings, Passage, PromptFragment, TurnRequest

ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = ROOT / "services" / "models-service"
DB = "ops_e13"
PG = f"postgresql+asyncpg://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/{DB}"
PORT = 8893
SERVICE = {"Authorization": "Bearer dev-service-token-not-secret"}
CALL_CAP = 10
QUESTION = "What is the daily wire limit for a personal account?"
# E8's plain turn ran on the runtime default.
REAL_MODEL = "gpt-5.5"


def out(line: str = "") -> None:
    print(line, flush=True)


def pct(values: list[float], q: int) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q / 100 * (len(ordered) - 1)))]


class NoTools:
    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        raise AssertionError("no tools in this experiment")


class NoKnowledge:
    async def search(self, query: str, kb_ids: list[str], *, k: int) -> list[Passage]:
        return []


def scripted() -> FunctionModel:
    async def stream(messages: list[Any], info: AgentInfo) -> AsyncIterator[str]:
        yield "The daily limit is $25,000."

    return FunctionModel(stream_function=stream)


async def turn(model: Model, alias: str) -> float:
    settings = AgentSettings("e13", 1, [PromptFragment("You answer briefly.")], alias)
    ports = KernelPorts(model, NoTools(), NoKnowledge())
    started = time.perf_counter()
    events = [e async for e in run_turn(TurnRequest("t", "th", settings, [], user_turn=QUESTION), ports)]
    elapsed = (time.perf_counter() - started) * 1000
    last = events[-1]
    assert isinstance(last, TurnFinished) and last.result.status == "completed", last
    return elapsed


async def group(model: Model, alias: str, n: int, concurrency: int) -> list[float]:
    gate = asyncio.Semaphore(concurrency)

    async def one() -> float:
        async with gate:
            return await turn(model, alias)

    await turn(model, alias)  # warm: connection and imports, not counted
    return list(await asyncio.gather(*(one() for _ in range(n))))


def line(label: str, ms: list[float]) -> str:
    return f"| {label} | {len(ms)} | {pct(ms, 50):.0f} / {pct(ms, 95):.0f} / {pct(ms, 99):.0f} | {statistics.mean(ms):.0f} |"


async def scratch_db() -> None:
    admin = await asyncpg.connect(f"postgresql://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/postgres")
    await admin.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
    await admin.execute(f"CREATE DATABASE {DB}")
    await admin.close()


def serve_models(env_extra: dict[str, str]) -> subprocess.Popen[bytes]:
    env = {k: v for k, v in os.environ.items() if k not in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VIRTUAL_ENV")}
    env.update({"OPS_DATABASE_URL": PG, "OPS_MODELS_PORT": str(PORT), **env_extra})
    subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"], cwd=MODELS_DIR, env=env, check=True, capture_output=True
    )
    log = open(ROOT / ".logs" / "e13-models.log", "ab")  # noqa: SIM115 - closed with the process
    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "ops_models"], cwd=MODELS_DIR, env=env, stdout=log, stderr=log
    )
    for _ in range(120):
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    proc.terminate()
    raise SystemExit("models-service did not start; see .logs/e13-models.log")


def issue_key(key_id: str) -> str:
    body = {"id": key_id, "kind": "purpose", "budget": "5", "rateLimitPerMinute": 1000}
    r = httpx.post(f"http://127.0.0.1:{PORT}/v1/models/keys", json=body, headers=SERVICE)
    r.raise_for_status()
    return str(r.json()["data"]["secret"])


async def part_scripted() -> None:
    proc = serve_models({})
    try:
        through = ModelsServiceModels(f"http://127.0.0.1:{PORT}", issue_key("purpose:e13-scripted"))
        out("## Scripted model: in process against through models-service (ms, p50 / p95 / p99)")
        out()
        out("| Group | Turns | Total | Mean |")
        out("|---|---|---|---|")
        for c in (1, 5):
            direct = await group(scripted(), "bank-standard", 50, c)
            hop = await group(through.model_for("bank-standard"), "bank-standard", 50, c)
            out(line(f"in process, concurrency {c}", direct))
            out(line(f"through models-service, concurrency {c}", hop))
            out(
                f"| hop at concurrency {c} (difference) | | {pct(hop, 50) - pct(direct, 50):.0f} / {pct(hop, 95) - pct(direct, 95):.0f} / - | |"
            )
        await through.client.close()
    finally:
        proc.terminate()


async def part_real() -> None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("the real part needs OPENAI_API_KEY")
    proc = serve_models({"OPS_MODEL_PROVIDER_KEYS": json.dumps({"OPENAI": key})})
    calls = 0
    try:
        conn = {
            "name": "openai-e13",
            "type": "openai-compatible",
            "baseUrl": "https://api.openai.com/v1",
            "keyRef": "OPENAI",
        }
        pid = httpx.post(f"http://127.0.0.1:{PORT}/v1/models/providers", json=conn, headers=SERVICE).json()["data"][
            "id"
        ]
        alias = {"name": "bank-live-e13", "providerId": pid, "modelId": REAL_MODEL, "clearedSensitivity": "internal"}
        httpx.post(f"http://127.0.0.1:{PORT}/v1/models/aliases", json=alias, headers=SERVICE).raise_for_status()
        through = ModelsServiceModels(f"http://127.0.0.1:{PORT}", issue_key("purpose:e13-real"))
        direct_model = OpenAIChatModel(REAL_MODEL, provider=OpenAIProvider(api_key=key))
        direct: list[float] = []
        hop: list[float] = []
        for _ in range(5):
            for model, sink, name in (
                (direct_model, direct, REAL_MODEL),
                (through.model_for("bank-live-e13"), hop, "bank-live-e13"),
            ):
                calls += 1
                if calls > CALL_CAP:
                    raise RuntimeError(f"real model call cap of {CALL_CAP} reached; stopping")
                sink.append(await turn(model, name))
        logged = httpx.get(
            f"http://127.0.0.1:{PORT}/v1/models/calls", params={"keyId": "purpose:e13-real"}, headers=SERVICE
        ).json()["data"]
        out(f"## Real model ({REAL_MODEL}), interleaved, {calls} calls (ms, p50 / p95 / p99)")
        out()
        out("| Group | Turns | Total | Mean |")
        out("|---|---|---|---|")
        out(line("direct", direct))
        out(line("through models-service", hop))
        out()
        totals = logged["byKey"][0] if logged["byKey"] else {}
        out(
            f"models-service logged {totals.get('calls')} calls costing {totals.get('cost')} at the alias's price (0 unless priced)"
        )
        tokens = [(c["inputTokens"], c["outputTokens"]) for c in logged["items"]]
        out(f"tokens per call through models-service (in, out): {tokens}")
        await through.client.close()
    finally:
        proc.terminate()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only", choices=["scripted", "real"])
    p.add_argument("--real-approved", action="store_true")
    args = p.parse_args()
    (ROOT / ".logs").mkdir(exist_ok=True)
    await scratch_db()
    if args.only in (None, "scripted"):
        await part_scripted()
    if args.only == "real":
        if not args.real_approved:
            raise SystemExit(
                "the real part makes up to 10 model calls; pass --real-approved once the owner has approved"
            )
        await part_real()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
