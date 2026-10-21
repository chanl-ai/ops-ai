"""Walks the seeded shared stack and proves it works, through the public API only (`make seed-walk`).

Prints, in order: each agent with its pinned guardrails, skills and knowledge bases; the published workflows (v1
registry workflows and v2 definitions) and which agents may call each as a tool. Then runs four checks, each ending
in a PASS or FAIL line with its evidence:

  0. every knowledge base and tool an agent names exists: its bases (and the bases callers may choose) in kb-service,
     its grants in the tool directory (no stale grant), so a seed never points at something the other seeds lack;
  a. a chat turn to ag_advisor that applies its hardship skill (always on, or loaded on match) and cites knowledge;
  b. a pair on ag_advisor's guardrail: a savings-product question answered, a shares question refused with the
     guardrail's message (the evidence says whether the pinned version carries its scope);
  c. a v2 workflow run through the queue to its end (a worker must be running: `scripts/stack.sh start worker`).

Each chat check also prints which provider and model served its turn, read from models-service's call log
(`/v1/models/calls`, joined to its aliases and providers) with a dev service token. When models-service is not
running, or the agents service calls a provider directly, the line says the call log could not be read.

Turns run on whatever model the stack routes to: the fake OpenAI with the committed demo rules
(services/models-service/seed/demo-fake-openai/script.json), or a real provider when an alias is bound to one.
Signs in through platform-service as James when it is up, else as a dev user. Exit status is the number of failed
checks.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

import httpx

AGENTS = f"http://127.0.0.1:{os.environ.get('OPS_AGENTS_PORT', '8700')}"
PLATFORM = f"http://127.0.0.1:{os.environ.get('OPS_PLATFORM_PORT', '8710')}"
MODELS = f"http://127.0.0.1:{os.environ.get('OPS_MODELS_PORT', '8730')}"
KB = f"http://127.0.0.1:{os.environ.get('OPS_KB_PORT', '8740')}"
TEAM = "team_ops"
JAMES, PASSWORD = "j.richardson@harborpine.example", "northfield-demo"
ADVISOR = "ag_advisor"
SKILLED = "My client lost her job. Compare Savings Plus and Money Market for her."
BLOCKED = "Should my client buy Harbor & Pine shares?"
# The bank's own deposit products: inside what the advisor answers, outside the guardrail's scoped topic.
SAVINGS = "What is the interest rate on Savings Plus, and how does it compare with Money Market?"
WALK_WORKFLOW = "walk_customer_lookup"
# A v2 definition the walk publishes if it is missing: a request, one read through the gateway, and an end.
DEFINITION = f"""
schemaVersion: 2
id: {WALK_WORKFLOW}
name: Customer lookup (seed walk)
nodes:
  - {{id: start, type: ops.trigger.request, typeVersion: 1, name: Request}}
  - id: lookup
    type: ops.action.tool
    typeVersion: 1
    name: Look up the customer
    parameters: {{operation: get_customer, input: {{customer_id: "$.input.customerId"}}}}
  - {{id: found, type: ops.flow.end, typeVersion: 1, name: Found, parameters: {{outcome: found}}}}
  - {{id: failed, type: ops.flow.end, typeVersion: 1, name: Failed, parameters: {{outcome: tool_failed}}}}
connections:
  - {{from: {{node: start, port: payload}}, to: {{node: lookup, port: in}}}}
  - {{from: {{node: lookup, port: ok}}, to: {{node: found, port: in}}}}
  - {{from: {{node: lookup, port: refused}}, to: {{node: failed, port: in}}}}
  - {{from: {{node: lookup, port: error}}, to: {{node: failed, port: in}}}}
"""

failed: list[str] = []


def result(name: str, ok: bool, evidence: Any) -> None:
    if not ok:
        failed.append(name)
    print(f"{'PASS' if ok else 'FAIL'} {name}")
    print(f"     {json.dumps(evidence, ensure_ascii=False)[:1200]}")


def headers() -> dict[str, str]:
    try:
        res = httpx.post(f"{PLATFORM}/v1/auth/sign-in", json={"email": JAMES, "password": PASSWORD}, timeout=10)
        token = res.json()["data"]["token"]
        print(f"signed in through platform-service as {JAMES}")
        return {"Authorization": f"Bearer {token}", "X-Team-Id": TEAM}
    except (httpx.HTTPError, KeyError, ValueError):
        print(f"platform-service did not sign in; using the dev user {JAMES}")
        return {"X-Dev-User": JAMES, "X-Team-Id": TEAM}


def data(res: httpx.Response) -> Any:
    if res.status_code >= 400:
        raise SystemExit(f"FAIL {res.request.method} {res.request.url.path}: {res.status_code} {res.text[:300]}")
    return res.json()["data"]


def frames(raw: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:].strip()))
            except ValueError:
                continue
    return out


def chat(api: httpx.Client, agent_id: str, question: str) -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    """One turn in a new conversation: the thread id, the final message (done or error frame) and every frame."""
    tid = data(api.post("/chat/threads", json={"agentId": agent_id, "kbIds": []}))["id"]
    res = api.post(
        f"/chat/threads/{tid}/messages",
        json={"content": question},
        headers={"Accept": "text/event-stream"},
        timeout=180,
    )
    events = frames(res.text)
    end = next((e for e in reversed(events) if e.get("type") in ("done", "error")), {})
    message = end.get("message") or end.get("partial") or {}
    if end.get("type") == "error":
        message = {**message, "error": end.get("message"), "errorCode": end.get("code")}
    return tid, message, events


def served_by(tid: str, since: str) -> dict[str, Any]:
    """Which provider and model answered the turn: models-service's call log rows for the thread, else every row
    written since the turn began (a chat turn may not name its thread), joined to the alias and its provider."""
    try:
        from ops_identity import mint_service_token  # noqa: PLC0415 - only this check needs the workspace
        from ops_identity.service_keys import dev_service_signer  # noqa: PLC0415

        token = mint_service_token(dev_service_signer(), service="agents", audience="models", tenant_id=TEAM)
        with httpx.Client(base_url=MODELS, headers={"Authorization": f"Bearer {token}"}, timeout=10) as m:
            rows: list[dict[str, Any]] = data(m.get("/v1/models/calls", params={"threadId": tid}))["items"]
            if not rows:
                recent = data(m.get("/v1/models/calls", params={"limit": 50}))["items"]
                rows = [r for r in recent if (r.get("createdAt") or "") >= since]
            aliases = {(a["name"], a["version"]): a for a in data(m.get("/v1/models/aliases"))}
            providers = {p["id"]: p for p in data(m.get("/v1/models/providers"))}
    except (httpx.HTTPError, SystemExit, ImportError, KeyError, ValueError) as e:
        return {"servedBy": f"models-service call log not readable at {MODELS}: {str(e)[:120]}"}
    seen: dict[str, int] = {}
    for r in rows:
        alias = aliases.get((r["alias"], r["aliasVersion"])) or {}
        p = providers.get(alias.get("providerId", "")) or {}
        via = f"via {r['alias']} v{r['aliasVersion']}"
        line = f"{p.get('name', '?')} ({p.get('type', '?')}) model {r['providerModel']} {via}"
        seen[line] = seen.get(line, 0) + 1
    return {"servedBy": [f"{line}: {n} call(s)" for line, n in seen.items()] or "no call logged for this turn"}


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def inventory(api: httpx.Client) -> None:
    print("\n== Agents: pinned guardrails, skills and knowledge bases")
    agents = data(api.get("/v1/agents", params={"pageSize": 200}))["data"]
    for a in agents:
        skills = data(api.get(f"/v1/agents/{a['id']}/skills"))["pins"]
        print(f"- {a['id']} {a['name']} v{a['version']} (published v{a['publishedVersion']}, {a['availability']})")
        pinned = [f"{p['name']} v{p['version']}" for p in a.get("guardrailPins") or []]
        held = [f"{p['name']} v{p['pinnedVersion']} ({p['loading']})" for p in skills]
        print(f"    guardrails: {', '.join(pinned) or 'none'}")
        print(f"    skills:     {', '.join(held) or 'none'}")
        print(f"    knowledge:  {', '.join(a.get('collections') or []) or 'none'}")
    callers: dict[str, list[str]] = {}
    for a in agents:
        for t in a.get("toolIds") or []:
            if t.startswith("workflow:"):
                callers.setdefault(t.removeprefix("workflow:"), []).append(a["id"])
    print("\n== Published workflows and the agents that may call each as a tool")

    def by(wid: str) -> str:
        return ", ".join(callers.get(wid, [])) or "no agent"

    # The list holds v2 definitions too (engine "v2"); those are listed from their own route below.
    for w in data(api.get("/v1/workflows", params={"pageSize": 200}))["data"]:
        if w.get("engine", "v1") == "v1" and w.get("status") not in ("deleted", "draft"):
            print(f"- v1 {w['id']} {w['name']} ({w['status']}): callable by {by(w['id'])}")
    defs = api.get("/v1/workflows/definitions", params={"pageSize": 200})
    rows = defs.json().get("data", {}).get("data", []) if defs.status_code == 200 else []
    for d in rows:
        about = f"v{d['version']} ({d['status']}, {d['runs']} runs)"
        print(f"- v2 {d['workflowId']} {d['name']} {about}: callable by {by(d['workflowId'])}")
    if defs.status_code != 200:
        print(
            f"- v2 definitions not served by this agents-service ({defs.status_code}); restart it on the current code"
        )


def references(api: httpx.Client) -> None:
    agents = data(api.get("/v1/agents", params={"pageSize": 200}))["data"]
    with httpx.Client(base_url=KB, headers=dict(api.headers), timeout=30) as kb:
        bases = {b["id"] for b in data(kb.get("/v1/knowledge-bases", params={"pageSize": 100}))["data"]}
    dangling: dict[str, dict[str, list[str]]] = {}
    for a in agents:
        limits: dict[str, Any] = a.get("limits") or {}
        named: set[str] = {*(a.get("collections") or []), *(limits.get("allowedKnowledgeBaseIds") or [])}
        stale: list[str] = a.get("staleToolIds") or []
        missing = {"knowledgeBases": sorted(named - bases), "tools": sorted(stale)}
        if any(missing.values()):
            dangling[a["id"]] = missing
    result("every knowledge base and tool an agent names exists", not dangling, dangling or {"agents": len(agents)})


def skill_and_citation(api: httpx.Client) -> None:
    since = now_utc()
    tid, m, _ = chat(api, ADVISOR, SKILLED)
    loaded = [f"{s['name']} v{s['version']} ({s.get('matched')})" for s in m.get("skills") or []]
    cites = [f"[{c.get('n')}] {c.get('title')} p.{c.get('page')}" for c in m.get("citations") or []]
    result(
        "a. ag_advisor applies its skill and cites knowledge",
        bool(loaded) and bool(cites) and not m.get("error"),
        {
            "thread": tid,
            "loaded": loaded,
            "citations": cites,
            "answer": (m.get("content") or "")[:240],
            "error": m.get("error"),
            **served_by(tid, since),
        },
    )


def blocked_topic(api: httpx.Client) -> None:
    """A pair on the advisor's guardrail: a question about the bank's own savings products is answered, and one about
    buying shares is refused before any answer. The pinned version's scope is what tells them apart, so the evidence
    says whether the version the advisor pins carries one."""
    advisor = data(api.get(f"/v1/agents/{ADVISOR}"))
    scoped: dict[str, bool] = {}
    pins: list[dict[str, Any]] = advisor.get("guardrailPins") or []
    for pin in pins:
        rule = data(api.get(f"/v1/guardrails/{pin['guardrailId']}"))
        scoped[f"{pin['name']} v{pin['version']}"] = (
            bool(rule.get("config", {}).get("scopes")) and rule.get("version") == pin["version"]
        )
    since = now_utc()
    saving_tid, saving, _ = chat(api, ADVISOR, SAVINGS)
    blocked_tid, blocked, _ = chat(api, ADVISOR, BLOCKED)
    answered = not saving.get("guardrail") and bool(saving.get("content")) and not saving.get("error")
    hit: dict[str, Any] = blocked.get("guardrail") or {}
    refused = hit.get("when") == "before" and bool(blocked.get("content"))
    result(
        "b. a savings question is answered and a shares question gets the guardrail's message",
        answered and refused,
        {
            "pinnedWithScope": scoped,
            "savings": {
                "thread": saving_tid,
                "guardrail": saving.get("guardrail"),
                "reply": (saving.get("content") or "")[:200],
            },
            "shares": {
                "thread": blocked_tid,
                "guardrail": blocked.get("guardrail"),
                "reply": (blocked.get("content") or "")[:200],
            },
            **served_by(blocked_tid, since),
        },
    )


def v2_run(api: httpx.Client) -> None:
    have = api.get(f"/v1/workflows/definitions/{WALK_WORKFLOW}")
    if have.status_code == 404:
        data(api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}))
        print(f"published the walk's v2 definition {WALK_WORKFLOW}")
    started = data(api.post("/v1/runs", json={"workflowId": WALK_WORKFLOW, "input": {"customerId": "CUS-1001"}}))
    run_id, run, deadline = started["runId"], {}, time.monotonic() + 90
    while time.monotonic() < deadline:
        run = data(api.get(f"/v1/runs/{run_id}"))
        if run["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    steps = [
        {"node": s.get("nodeId"), "status": s.get("status"), "port": s.get("port"), "output": s.get("output")}
        for s in run.get("steps") or []
    ]
    hint = (
        "the run is still queued: start a worker with `scripts/stack.sh start worker`"
        if run.get("status") == "queued"
        else None
    )
    result(
        "c. a v2 workflow run goes through the queue to its end",
        run.get("status") == "succeeded" and run.get("outcome") == "found",
        {
            "run": run_id,
            "status": run.get("status"),
            "outcome": run.get("outcome"),
            "steps": steps,
            "error": run.get("error"),
            "hint": hint,
        },
    )


def main() -> int:
    with httpx.Client(base_url=AGENTS, headers=headers(), timeout=60) as api:
        inventory(api)
        print("\n== Checks")
        references(api)
        skill_and_citation(api)
        blocked_topic(api)
        v2_run(api)
    print(f"\n{4 - len(failed)} of 4 checks passed")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
