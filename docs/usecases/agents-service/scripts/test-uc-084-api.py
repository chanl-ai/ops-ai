"""uc-084 an agent finds and runs a workflow whose agent step answers by schema, api layer:
docs/usecases/agents-service/agent-runs-a-workflow-by-search.md. The banker demo's stack (harness demo(): models-service
on the fake OpenAI with the committed demo rules, tools-service and the core bank, kb-service) plus a workflow runner
worker. ag_advisor holds workflow:customer_summary, the seeded v2 workflow whose `summarise` step runs ag_advisor with
the output schema {customerId, summary}. No real model is called.

Set UC084_UNGRANTED=1 to drop the grant before the first chat: the search then finds nothing and the checks fail."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_DIR,
    DB,
    KB_PORT,
    LOG_DIR,
    MODELS_PORT,
    TOOLS_PORT,
    _env,  # pyright: ignore[reportPrivateUsage]
    chat,
    check,
    data,
    demo,
    finish,
    turn_text,
)

AGENT = "ag_advisor"
WORKFLOW = "customer_summary"
ASK = "Run the customer summary workflow for Priya Natarajan."
DIRECT = "Start the customer summary workflow directly for Priya Natarajan."
OPS = {"X-Team-Id": "team_ops"}


@contextmanager
def worker() -> Generator[subprocess.Popen[bytes]]:
    """A worker with the agents service's settings: the run's database, the gateway, models-service and kb-service."""
    env = _env()
    pg = os.environ.get("OPS_PG_PORT", "5477")
    env |= {
        "OPS_DATABASE_URL": f"postgresql+asyncpg://ops:ops@localhost:{pg}/{DB}",
        "OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}",
        "OPS_MODELS_URL": f"http://127.0.0.1:{MODELS_PORT}",
        "OPS_MODELS_KEY": "mk_dev_agents",
        "OPS_KB_URL": f"http://127.0.0.1:{KB_PORT}",
        "OPS_AGENTS_SEED_FILE": "seed/chat_agents.json",
        "OPS_ENGINE_POLL_SECONDS": "0.2",
    }
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "worker-uc084.log").open("ab") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "ops_agents.api.worker"], cwd=AGENTS_DIR, env=env, stdout=fh, stderr=fh
        )
    try:
        yield proc
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


def calls(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [e["call"] for e in events if e.get("type") == "tool_end" and e["call"]["name"] == name]


def grant(api: httpx.Client, *, on: bool) -> int:
    tools: list[str] = list(data(api.get(f"/v1/agents/{AGENT}", headers=OPS))["toolIds"])
    wanted = f"workflow:{WORKFLOW}"
    tools = [t for t in tools if t != wanted] + ([wanted] if on else [])
    patched = api.patch(f"/v1/agents/{AGENT}", json={"toolIds": tools}, headers=OPS)
    if patched.status_code != 200:
        return patched.status_code
    # A save is a new version; the live agent changes once it is published (dev approves its own request).
    body = {"version": data(patched)["version"], "note": "uc-084 grant"}
    return api.post(f"/v1/agents/{AGENT}/publish-requests", json=body, headers=OPS).status_code


def main() -> None:
    with demo() as d, worker():
        api = d.api
        listed = {t["id"]: t for t in data(api.get("/v1/tools", headers=OPS))}
        check(
            "the seeded v2 workflow is in the tool directory with its input schema",
            f"workflow:{WORKFLOW}" in listed
            and listed[f"workflow:{WORKFLOW}"]["inputSchema"].get("required") == ["customer"],
            sorted(listed)[:20],
        )
        if os.environ.get("UC084_UNGRANTED") == "1":
            grant(api, on=False)
        held = data(api.get(f"/v1/agents/{AGENT}", headers=OPS))["toolIds"]
        check(f"{AGENT} holds workflow:{WORKFLOW}", f"workflow:{WORKFLOW}" in held, held)

        _, events = chat(api, AGENT, ASK)
        searched = calls(events, "search_tools")
        check(
            "the agent searches its tools and finds the workflow",
            bool(searched) and f"workflow__{WORKFLOW}" in json.dumps(searched[0].get("output")),
            searched,
        )
        started = calls(events, f"workflow__{WORKFLOW}")
        out: dict[str, Any] = dict(started[0].get("output") or {}) if started else {}
        outcome: dict[str, Any] = dict(out.get("outcome") or {})
        check(
            "it starts the workflow and the run's outcome comes back: customer id and summary",
            bool(started)
            and started[0]["status"] == "success"
            and out.get("status") == "finished"
            and isinstance(out.get("runId"), str)
            and outcome.get("customerId") == "CUS-1002"
            and "Priya Natarajan" in str(outcome.get("summary")),
            out,
        )
        text = turn_text(events)
        check("the chat answers with the workflow's summary", "Priya Natarajan" in text, text[:300])

        run = data(api.get(f"/v1/runs/{out.get('runId')}", headers=OPS)) if out.get("runId") else {}
        steps = {s["nodeId"]: s for s in (run or {}).get("steps", [])}
        step = steps.get("summarise", {})
        check(
            "the run finds the customer by name and reads their record before the agent step",
            [steps.get(k, {}).get("port") for k in ("find", "found", "read")] == ["ok", "true", "ok"],
            {k: steps.get(k, {}).get("port") for k in ("find", "found", "read")},
        )
        check(
            "the run's agent step reads the input and returns the schema's output through the ok port",
            (run or {}).get("outcome") == "summarised"
            and step.get("port") == "ok"
            and step.get("input", {}).get("input", {}).get("customer") == "Priya Natarajan"
            and step.get("input", {}).get("input", {}).get("record", {}).get("id") == "CUS-1002"
            and step.get("output") == outcome,
            {"run": (run or {}).get("status"), "step": step},
        )

        # Taken out of the agent's tools, the workflow is not found by search, and nothing starts.
        check("ungranting the workflow is saved and published", grant(api, on=False) in (200, 201))
        _, events = chat(api, AGENT, ASK)
        searched = calls(events, "search_tools")
        found = json.dumps(searched[0].get("output")) if searched else ""
        check(
            "ungranted, search_tools does not find it", bool(searched) and f"workflow__{WORKFLOW}" not in found, found
        )
        # The model calls the workflow by name anyway (a forced fake rule): the call is refused and no run starts.
        before = data(api.get("/v1/runs", params={"workflowId": WORKFLOW}, headers=OPS))["pagination"]["total"]
        _, events = chat(api, AGENT, DIRECT)
        ran = [c for c in calls(events, f"workflow__{WORKFLOW}") if c["status"] == "success"]
        after = data(api.get("/v1/runs", params={"workflowId": WORKFLOW}, headers=OPS))["pagination"]["total"]
        check(
            "ungranted, a direct call to the workflow is refused and starts no run",
            not ran and after == before,
            {"ran": ran, "runs": (before, after), "text": turn_text(events)[:200]},
        )
    finish()


if __name__ == "__main__":
    main()
