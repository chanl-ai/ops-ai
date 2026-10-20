# ruff: noqa: E501
# pyright: reportUnknownMemberType=false
# Printed lines are the experiment's record and stay whole; LangGraph's compiled graph methods are partially untyped.
"""Experiment 1: does a thread paused for days survive a graph change?

Runs through the real /v1 routes in-process, with deterministic model calls and an in-memory checkpointer, so the
output is reproducible. Prints every step for experiments/pause-survives-graph-change.md.

  uv run python experiments/e1_pause_survives_graph_change.py
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agent_kernel.ports import KernelPorts
from ops_agents.activities.catalog import load_catalog
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor
from ops_agents.api.app import create_app
from ops_agents.graphs.common import GraphDeps
from ops_agents.graphs.definition import WorkflowDefinition, compile_definition
from ops_agents.store.graphs import metadata
from ops_service_kit.settings import Settings
from tests.knowledge_fixture import KeywordPassageStore

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.conftest import SEED, FakeGraphModels, scripted_model, sse_events  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
EMAIL: dict[str, Any] = json.loads((FIX / "seed" / "dispute_emails.json").read_text())[1]


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")


def definition(version: int) -> dict[str, Any]:
    if version == 1:
        return json.loads((FIX / "seed" / "workflows.json").read_text())[0]
    return json.loads((FIX / "workflows" / f"dispute_email.v{version}.json").read_text())


async def api_part() -> None:
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
    app = create_app(
        settings, model=scripted_model(), engine=engine, checkpointer=InMemorySaver(), graph_models=FakeGraphModels()
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://e1") as c,
    ):

        async def call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
            res = await c.request(method, path, json=body)
            if "runs/stream" in path:
                events = sse_events(res.text) if res.status_code == 200 else []
                status = events[-1]["data"]["status"] if events else res.json()["error"]
                out(f"{method} {path} -> {res.status_code} end={status}")
                return events
            payload = res.json()
            shown = payload.get("data") if payload.get("success") else payload["error"]
            out(f"{method} {path} -> {res.status_code} {json.dumps(shown)[:220]}")
            return shown

        out("## 1. Start at version 1 and pause at the human step")
        t1 = (await call("POST", "/v1/threads", {"graph": "dispute_email"}))["threadId"]
        await call("POST", f"/v1/threads/{t1}/runs/stream", {"input": {"email": EMAIL}})
        out(
            "\n## 2. Publish version 2 (compliance_check after draft; grade renamed score) and version 3 (human renamed review)"
        )
        await call("POST", "/v1/graphs/dispute_email/versions", {"definition": definition(2)})
        await call("POST", "/v1/graphs/dispute_email/versions", {"definition": definition(3)})
        out("\n## 3. Resume the paused v1 thread")
        await call("POST", f"/v1/threads/{t1}/runs/stream", {"resume": {"decision": "approved"}})
        s1 = (await c.get(f"/v1/threads/{t1}/state")).json()["data"]
        out(f"state {t1}: version={s1['version']} status={s1['values']['status']} next={s1['next']}")
        out(f"  visited: {s1['values']['visited']}")
        out("\n## 4. A new thread pinned to version 2")
        t2 = (await call("POST", "/v1/threads", {"graph": "dispute_email", "version": 2}))["threadId"]
        await call("POST", f"/v1/threads/{t2}/runs/stream", {"input": {"email": EMAIL}})
        s2 = (await c.get(f"/v1/threads/{t2}/state")).json()["data"]
        out(f"state {t2}: version={s2['version']} next={s2['next']}")
        out(f"  visited: {s2['values']['visited']}")
        out("\n## 5. Migration: refused to v3 (no node named human), allowed to v2, then resumed")
        t3 = (await call("POST", "/v1/threads", {"graph": "dispute_email", "version": 1}))["threadId"]
        await call("POST", f"/v1/threads/{t3}/runs/stream", {"input": {"email": EMAIL}})
        await call("POST", f"/v1/threads/{t3}/migrate", {"toVersion": 3})
        await call("POST", f"/v1/threads/{t3}/migrate", {"toVersion": 2})
        await call("POST", f"/v1/threads/{t3}/runs/stream", {"resume": {"decision": "approved"}})
        s3 = (await c.get(f"/v1/threads/{t3}/state")).json()["data"]
        out(f"state {t3}: version={s3['version']} status={s3['values']['status']}")
        out(f"  visited: {s3['values']['visited']}")
        await call("POST", f"/v1/threads/{t3}/migrate", {"toVersion": 2})


def deps() -> GraphDeps:
    catalog = load_catalog(SEED)
    ports = KernelPorts(scripted_model(), LocalToolExecutor(catalog), KeywordPassageStore(catalog))
    return GraphDeps(catalog, ports, FakeGraphModels(), LocalReplySender(), "m")


async def negative_control() -> None:
    out("\n## 6. Negative control: resume a v1-paused thread on another version's graph directly (no pin)")
    v1 = WorkflowDefinition.model_validate(definition(1))
    for version in (2, 3):
        target = WorkflowDefinition.model_validate(definition(version))
        saver = InMemorySaver()
        cfg: Any = {"configurable": {"thread_id": f"neg-v{version}"}}
        await compile_definition(v1, deps(), saver).ainvoke({"email": EMAIL}, cfg)
        g = compile_definition(target, deps(), saver)
        before = await g.aget_state(cfg)
        out(
            f"v{version}: paused at {before.next}; pending interrupts seen through the v{version} graph: {len(before.interrupts)}"
        )
        try:
            result = await g.ainvoke(Command(resume={"decision": "approved"}), cfg)
            after = await g.aget_state(cfg)
            out(
                f"v{version}: ainvoke raised nothing; returned status={result.get('status')!r} sent={result.get('sent')!r}"
            )
            out(
                f"v{version}: after: next={after.next} interrupts={len(after.interrupts)} visited={after.values.get('visited')}"
            )
        except Exception as e:
            out(f"v{version}: raised {type(e).__name__}: {e}")


def latency() -> None:
    out("\n## 7. Compile cost")
    for version in (1, 2):
        d = WorkflowDefinition.model_validate(definition(version))
        times: list[float] = []
        for _ in range(50):
            started = time.perf_counter()
            compile_definition(d, deps(), None)
            times.append((time.perf_counter() - started) * 1000)
        out(f"v{version}: compile {statistics.median(times):.2f} ms median, {max(times):.2f} ms max over 50 (no cache)")
    from ops_agents.graphs.definition import CompiledCache  # noqa: PLC0415

    cache = CompiledCache(deps(), None)
    d = WorkflowDefinition.model_validate(definition(1))
    cache.get(d)
    started = time.perf_counter()
    for _ in range(1000):
        cache.get(WorkflowDefinition.model_validate(definition(1)))
    per = (time.perf_counter() - started) / 1000 * 1000
    out(
        f"cache hit incl. parsing the stored JSON and hashing it: {per:.3f} ms; compiles after 1001 gets: {cache.compiles}"
    )


async def main() -> None:
    await api_part()
    await negative_control()
    latency()


if __name__ == "__main__":
    asyncio.run(main())
