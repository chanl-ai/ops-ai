"""uc-231 a Calculate step works out a levy's amount and deadline, api layer:
docs/usecases/agents-service/calculate-a-levy-amount-and-deadline.md. A real worker runs the workflow and tools-service
evaluates the formulas in its sandbox (POST /v1/expressions/evaluate). No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import (
    AGENTS_PORT,
    TEAM,
    TOOLS_PORT,
    agents,
    check,
    data,
    engine_worker,
    finish,
    service_headers,
    tools,
    until,
)

DEFINITION = """
schemaVersion: 2
id: uc231_levy_amount
name: Levy amount and deadline (uc-231)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Notice}
  - id: calc
    type: ops.data.compute
    typeVersion: 1
    name: Amount and deadline
    parameters:
      values: {levy: "$.input.levy", balance: "$.input.balance"}
      expressions:
        amount: "min(levy.amount, balance)"
        short: "levy.amount - amount"
        deadline: "business_days(levy.served, 20)"
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Done, parameters: {outcome: done, output: "$.nodes.calc.out"}}
  - id: failed
    type: ops.flow.end
    typeVersion: 1
    name: Failed
    parameters: {outcome: formula_failed, output: "$.nodes.calc.out"}
connections:
  - {from: {node: start, port: payload}, to: {node: calc, port: in}}
  - {from: {node: calc, port: out}, to: {node: done, port: in}}
  - {from: {node: calc, port: error}, to: {node: failed, port: in}}
"""
# Served on a Friday: twenty working days later is Friday 13 November.
NOTICE = {"levy": {"amount": 3250.0, "served": "2026-10-16", "note": "levy.__class__"}, "balance": 1800}


def finished(api: httpx.Client, key: str, payload: dict[str, Any]) -> dict[str, Any]:
    res = api.post("/v1/runs", json={"workflowId": "uc231_levy_amount", "input": payload, "runKey": key}, headers=TEAM)
    run_id = str(data(res)["runId"])

    def done() -> dict[str, Any] | None:
        run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
        return run if run.get("status") in ("succeeded", "failed") else None

    return until(done) or {"runId": run_id}


with ExitStack() as stack:
    gw = stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=TEAM)
    check(
        "1 the definition with a Calculate step saves with every check passing",
        created.status_code == 201,
        created.text[:300],
    )
    live = api.post("/v1/workflows/definitions/uc231_levy_amount/publish-requests", json={}, headers=TEAM)
    check("1 its version goes live", data(live)["status"] == "approved", live.text[:200])

    # 2. A formula with a path in it is refused on save: data reaches formulas only as values.
    bad = DEFINITION.replace("uc231_levy_amount", "uc231_bad").replace(
        '"min(levy.amount, balance)"', '"$.input.balance * 2"'
    )
    refused = api.post("/v1/workflows/definitions", json={"yaml": bad}, headers=TEAM)
    check(
        "2 a formula holding a path is refused on save",
        refused.status_code in (400, 422) and "expressions" in refused.text,
        refused.text[:300],
    )

    stack.enter_context(engine_worker("uc231", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))
    # 3. The worker runs it: the gateway's sandbox works out the amount and the deadline.
    run = finished(api, "uc231-a", NOTICE)
    out = (run.get("result") or {}).get("output")
    check("3 the run succeeds at its done end", (run.get("status"), run.get("outcome")) == ("succeeded", "done"), run)
    want = {"amount": 1800, "short": 1450.0, "deadline": "2026-11-13"}
    check(
        "3 amount, shortfall and deadline are worked out, numbers as numbers",
        out == want and isinstance(out["amount"], int),
        out,
    )

    # 4. A notice with no amount takes the error port, and the run says which formula failed.
    broken = finished(api, "uc231-b", {"levy": {"served": "2026-10-16"}, "balance": 1800})
    why = str(broken)
    check(
        "4 a formula over a missing field ends on the error port, naming the formula",
        "formula_failed" in why and "amount:" in why,
        why[:400],
    )

    # 5. The route the step calls refuses a service without the tools scope.
    no_scope = gw.post(
        "/v1/expressions/evaluate", json={"expressions": {"a": "1"}}, headers=service_headers("tools", team="team_ops")
    )
    check("5 a service without tools:view may not evaluate", no_scope.status_code == 403, no_scope.text[:200])

finish()
