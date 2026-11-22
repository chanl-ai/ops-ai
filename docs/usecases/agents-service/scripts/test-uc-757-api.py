# The use case runner puts docs/usecases/lib (usecase_harness) on the path; pyright alone cannot see it.
# pyright: basic, reportMissingImports=false
"""uc-757 a run outlives a killed worker and redrives from its failed step, api layer:
docs/usecases/agents-service/a-run-outlives-a-killed-worker.md.

Own services, no real model: platform-service for the team's aiSteps setting, models-service on the fake OpenAI with
the AI step rules (agents-service tests/fixtures/ai-steps-fake-openai), tools-service as the gateway with the core bank
fake behind it, agents-service, and workflow workers this script starts and kills. The bank holds a note write open
while its author reads `slow:<seconds>:`, so the kill lands while the write is in flight.

Step 3 is the non-vacuous check: with the engine's settling of a dangling write by its key removed
(packages/ops_engine/src/ops_engine/compiler.py, the `last.status in ("running", "error")` branch), the replacement
worker sends the held write again under a new key and the bank gets a third note."""

from __future__ import annotations

import os
import signal
import subprocess
import uuid
from collections.abc import Callable
from contextlib import ExitStack
from typing import Any

import httpx
from ai_steps_stack import RULES
from usecase_harness import (
    AGENTS_PORT,
    TOOLS_PORT,
    agents,
    approve_tool_review,
    bearer,
    check,
    core_bank,
    data,
    engine_worker,
    every_page,
    fake_openai,
    finish,
    models,
    platform,
    service_headers,
    signed_in,
    tools,
    until,
)

OPS = {"X-Team-Id": "team_ops"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
MODELS_ADMIN = service_headers("models")
RUN = uuid.uuid4().hex[:6]
WID = f"uc757_note_{RUN}"
HOLD_S = 3
BODY = "UC259-NOTE Priya Natarajan called: please close savings account 4471 by 30 November 2026."


def note(nid: str, text: str, author: str) -> dict[str, Any]:
    args = {"customer_id": "$.input.customerId", "text": text, "author": author}
    params = {"operation": "add_customer_note", "input": args}
    return {"id": nid, "type": "ops.action.tool", "typeVersion": 1, "name": nid, "parameters": params}


# Note the call, summarise it (one model call), then write the summary on the customer's record, held open.
SUMMARY = {
    "id": "summary",
    "type": "ops.ai.summarise",
    "typeVersion": 1,
    "name": "Summarise",
    "parameters": {"text": "$.input.body"},
}
NODES = [
    {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request"},
    note("logged", "$.input.body", "uc-757"),
    SUMMARY,
    note("filed", "$.nodes.summary.out.summary", f"slow:{HOLD_S}:uc-757"),
    {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {"outcome": "filed"}},
    {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "name": "Failed", "parameters": {"outcome": "failed"}},
]
WIRES = [("start", "payload", "logged"), ("logged", "ok", "summary"), ("summary", "ok", "filed"), ("filed", "ok", "done")]
WIRES += [(n, p, "failed") for n in ("logged", "filed") for p in ("refused", "error")]
WIRES += [("summary", "error", "failed")]
DEFINITION = {
    "schemaVersion": 2,
    "id": WID,
    "name": "Note a call (uc-757)",
    "nodes": NODES,
    "connections": [{"from": {"node": f, "port": p}, "to": {"node": t, "port": "in"}} for f, p, t in WIRES],
}


def bank_module(gw: httpx.Client, host: str) -> None:
    """The core bank as a published module whose note write runs without an approval."""
    source = {"kind": "openapi", "specUrl": f"https://{host}/openapi.json"}
    found = data(gw.post("/v1/tool-modules/discover", json=source))
    ops = [
        {**o, "access": "read" if (o.get("method") or "GET").upper() == "GET" else "write"} for o in found["operations"]
    ]
    body = {
        "name": f"uc757-bank-{RUN}",
        "displayName": "Core Banking (uc-757)",
        "system": found["system"],
        "type": "openapi",
        "endpoint": found["endpoint"],
        "operations": ops,
        "source": source,
    }
    made = data(gw.post("/v1/tool-modules", json=body))
    op = next(o for o in made["operations"] if o["name"] == "add_customer_note")
    data(gw.patch(f"/v1/tool-modules/{made['id']}/operations/{op['id']}", json={"requiresApproval": False}))
    data(gw.post(f"/v1/tool-modules/{made['id']}/reviews", json={"note": "uc-757"}))
    approve_tool_review(gw, made["id"], SECURITY)


def run_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    return data(api.get(f"/v1/runs/{run_id}", headers=OPS)) or {}


def step(run: dict[str, Any], node: str) -> list[dict[str, Any]]:
    return [s for s in run.get("steps", []) if s.get("nodeId") == node]


def writes(gw: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    return [r for r in every_page(gw, "/v1/executions", thread=run_id) if r["target"] == "add_customer_note"]


def fresh(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The writes that reached the system: a key the gateway answered again from its record is not one."""
    return [r for r in rows if r.get("status") != "replayed" and not r.get("replayOf")]


def model_calls(admin: httpx.Client, run_id: str) -> list[dict[str, Any]]:
    calls = every_page(admin, "/v1/models/calls", headers=MODELS_ADMIN)
    return [c for c in calls if str(c.get("runId") or "").startswith(run_id)]


def kill_worker(proc: subprocess.Popen[bytes]) -> bool:
    """SIGKILL to the worker itself (the Python process under `uv run`), then to uv; True once the worker is gone."""
    found = subprocess.run(["pgrep", "-P", str(proc.pid)], capture_output=True, text=True, check=False).stdout.split()
    for pid in [*found, str(proc.pid)]:
        try:
            os.kill(int(pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait(timeout=10)

    def gone() -> bool:
        # A killed child stays a zombie until init reaps it; `ps -o stat=` reads Z (or nothing) for one that is dead.
        stats = [subprocess.run(["ps", "-o", "stat=", "-p", p], capture_output=True, text=True).stdout for p in found]
        return all(not st.strip() or st.strip().startswith("Z") for st in stats)

    return bool(found) and bool(until(gone, 10))


def ended(api: httpx.Client, run_id: str, *wanted: str) -> Callable[[], dict[str, Any] | None]:
    def probe() -> dict[str, Any] | None:
        r = run_of(api, run_id)
        return r if r.get("status") in (wanted or ("succeeded", "failed", "cancelled")) else None

    return probe


def in_flight(api: httpx.Client, run_id: str) -> Callable[[], dict[str, Any] | None]:
    def probe() -> dict[str, Any] | None:
        return next((s for s in step(run_of(api, run_id), "filed") if s["status"] == "running"), None)

    return probe


def main() -> None:
    with ExitStack() as stack:
        people, _inner = stack.enter_context(platform())
        fake = stack.enter_context(fake_openai(RULES))
        model_stack = stack.enter_context(ExitStack())
        models_url = model_stack.enter_context(models({"OPS_MODELS_FAKE_OPENAI_URL": fake}))
        bank = stack.enter_context(core_bank())
        platform_url = str(people.base_url).rstrip("/")
        gateway = f"http://127.0.0.1:{TOOLS_PORT}"
        agents_url = f"http://127.0.0.1:{AGENTS_PORT}"
        gw = stack.enter_context(tools(bank["settings"] | {"OPS_AGENTS_URL": agents_url}, approval_rules=True))
        api = stack.enter_context(
            agents(
                gateway_url=gateway,
                models_url=models_url,
                models_key="mk_dev_agents",
                env={"OPS_PLATFORM_URL": platform_url},
            )
        )
        admin = stack.enter_context(httpx.Client(base_url=models_url, timeout=30))
        gw.post("/v1/egress/hosts", json={"value": bank["host"], "note": "uc-757"})
        gw.post("/v1/egress/ranges", json={"value": bank["range"], "note": "uc-757"})
        gw.post("/v1/secrets", json={"name": "BANK_API_KEY", "value": "dev-bank-key"}, headers=OPS)
        bank_module(gw, bank["host"])
        priya = bearer(signed_in(people, "p.shah@harborpine.example"), "team_ops")
        people.put("/v1/policies/aiSteps", json={"value": True}, headers=priya)
        saved = api.post("/v1/workflows/definitions", json={"definition": DEFINITION}, headers=OPS)
        live = data(api.post(f"/v1/workflows/definitions/{WID}/publish-requests", json={}, headers=OPS)) or {}
        check("setup the workflow goes live", live.get("status") == "approved", saved.text[:300])
        env = {
            "OPS_GATEWAY_URL": gateway,
            "OPS_MODELS_URL": models_url,
            "OPS_MODELS_KEY": "mk_dev_agents",
            "OPS_PLATFORM_URL": platform_url,
            "OPS_LEASE_TTL_SECONDS": "3",
        }
        start = {"workflowId": WID, "mode": "live", "input": {"customerId": "CUS-1001", "body": BODY}}

        # 1. A run starts; its worker is killed while the summary's write is held open at the bank.
        first = str(data(api.post("/v1/runs", json=start, headers=OPS))["runId"])
        with engine_worker(f"uc757-a-{RUN}", env) as doomed:
            mid = until(in_flight(api, first), 90)
            gone = kill_worker(doomed) if mid else False
        killed = run_of(api, first)
        filed = step(killed, "filed")
        check(
            "1 the worker is killed by SIGKILL mid-step: its write is in flight and the run has not moved on",
            bool(mid) and gone and killed.get("status") == "running" and bool(filed) and filed[-1]["status"] == "running",
            {"status": killed.get("status"), "filed": [s.get("status") for s in filed], "gone": gone},
        )

        # 2. A replacement worker takes the run over and finishes it; the run page shows it filed.
        with engine_worker(f"uc757-b-{RUN}", env):
            until(ended(api, first), 120 + HOLD_S)
            page = run_of(api, first)
            check(
                "2 the replacement worker finishes the run and its page shows the summary filed",
                page.get("status") == "succeeded"
                and page.get("outcome") == "filed"
                and [s.get("port") for s in step(page, "filed")][-1:] == ["ok"],
                {"status": page.get("status"), "outcome": page.get("outcome"), "error": page.get("error")},
            )
            # 3. Across the kill the model answered the summary once and the gateway ran each write once.
            sent, asked = fresh(writes(gw, first)), model_calls(admin, first)
            check(
                "3 the model saw the summary call once and the gateway each of the two writes once",
                len(asked) == 1 and len(sent) == 2,
                {"model calls": len(asked), "writes": [(w.get("step"), w.get("status")) for w in sent]},
            )

        # 4. A second run whose worker dies on the summary every time: after seven workers the reconciler marks it
        # Stuck, with its first note written once.
        second = str(data(api.post("/v1/runs", json=start, headers=OPS))["runId"])
        dying = {"OPS_ENGINE_FAULT_KILL_AFTER_NODE": "summary", "OPS_ENGINE_FAULT_IGNORE_RECORDED": "1"}
        for i in range(7):
            with engine_worker(f"uc757-dying-{i}-{RUN}", env | dying) as doomed:
                until(doomed.poll, 90)
        with engine_worker(f"uc757-marking-{RUN}", env | {"OPS_ENGINE_RECONCILE_SECONDS": "2"}):
            stuck = until(ended(api, second, "stuck", "failed"), 90) or {}
        check(
            "4 a run whose worker keeps dying on its summary stops as Stuck, offering Redrive, its first note written once",
            stuck.get("status") == "stuck" and stuck.get("canRedrive") is True and len(fresh(writes(gw, second))) == 1,
            {"status": stuck.get("status"), "canRedrive": stuck.get("canRedrive"), "error": stuck.get("error")},
        )

        # 5. Redrive with a healthy worker goes on from the summary and runs no finished step again.
        with engine_worker(f"uc757-c-{RUN}", env):
            redriven = api.post(f"/v1/runs/{second}/redrive", headers=OPS)
            finished = until(ended(api, second), 120 + HOLD_S) or {}
        page = run_of(api, second)
        tries = {n: sum(len(s.get("attempts") or [s]) for s in step(page, n)) for n in ("logged", "filed")}
        sent2, asked2 = fresh(writes(gw, second)), model_calls(admin, second)
        check(
            "5 Redrive finishes the run from its failed step; no note is written twice and the model is asked once",
            redriven.status_code == 200
            and finished.get("outcome") == "filed"
            and tries == {"logged": 1, "filed": 1}
            and len(sent2) == 2
            and len(asked2) == 1,
            {
                "redrive": redriven.status_code,
                "outcome": finished.get("outcome"),
                "attempts": tries,
                "writes": [(w.get("step"), w.get("status")) for w in writes(gw, second)],
                "model calls": len(asked2),
            },
        )
    finish()


if __name__ == "__main__":
    main()
