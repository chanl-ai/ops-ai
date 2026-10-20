"""uc-251 a case reads assembled, api layer: docs/usecases/agents-service/a-case-reads-assembled.md.

A real worker runs a fee dispute workflow (configuration below, nothing in code knows it): it opens a case of the
seeded `complaint` type and waits on a person to approve waiving the fee. The case page's one call says what the case
waits on, the drafted action, its typed fields and its links; once the task is approved on its own page, the case
reads the action decided and the decision in its activity. No model call is made."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any

import httpx
from usecase_harness import AGENTS_PORT, TEAM, TOOLS_PORT, agents, check, data, engine_worker, finish, tools, until

DEFINITION = """
schemaVersion: 2
id: uc251_fee_dispute
name: Fee dispute (uc-251)
nodes:
  - {id: start, type: ops.trigger.request, typeVersion: 1, name: Dispute}
  - id: open
    type: ops.action.openCase
    typeVersion: 1
    name: Open a case
    parameters:
      subject: "Fee dispute from {$.input.customerName}"
      priority: high
      customerId: "$.input.customerId"
      customerName: "$.input.customerName"
      caseType: complaint
      fields: {amount: "$.input.amount", complaint: "$.input.complaint", category: fees}
  - id: review
    type: ops.flow.humanReview
    typeVersion: 1
    name: Approve waiving the fee
    parameters: {title: "Waive {$.input.amount} for {$.input.customerName}", approves: waive}
  - id: waive
    type: ops.action.tool
    typeVersion: 1
    name: Waive the fee
    parameters:
      operation: waive_fee
      approvedBy: review
      input: {cardAccount: "$.input.cardAccount", feeId: "$.input.feeId", amount: "$.input.amount"}
  - {id: done, type: ops.flow.end, typeVersion: 1, name: Waived, parameters: {outcome: waived}}
  - {id: declined, type: ops.flow.end, typeVersion: 1, name: Declined, parameters: {outcome: declined}}
  - id: failed
    type: ops.flow.end
    typeVersion: 1
    name: Could not finish
    parameters: {outcome: failed, result: failed}
connections:
  - {from: {node: start, port: payload}, to: {node: open, port: in}}
  - {from: {node: open, port: opened}, to: {node: review, port: in}}
  - {from: {node: open, port: error}, to: {node: failed, port: in}}
  - {from: {node: review, port: approve}, to: {node: waive, port: in}}
  - {from: {node: review, port: reject}, to: {node: declined, port: in}}
  - {from: {node: waive, port: ok}, to: {node: done, port: in}}
  - {from: {node: waive, port: refused}, to: {node: failed, port: in}}
  - {from: {node: waive, port: error}, to: {node: failed, port: in}}
"""
LETTER = "fil_" + "a1" * 16
DISPUTE: dict[str, Any] = {
    "customerId": "CUS-118842",
    "customerName": "Marcus Bell",
    "cardAccount": "CARD-4471",
    "feeId": "FEE-3901",
    "amount": "35",
    "complaint": "Charged a late fee after paying on time",
    "letter": {"fileId": LETTER, "name": "dispute-letter.pdf"},
}


def case_of(api: httpx.Client, run_id: str) -> dict[str, Any]:
    run = data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}
    opened = next((s for s in run.get("steps") or [] if s.get("nodeId") == "open"), {})
    case_id = (opened.get("output") or {}).get("caseId")
    return data(api.get(f"/v1/cases/{case_id}", headers=TEAM)) if case_id else {}


with ExitStack() as stack:
    stack.enter_context(tools({"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}))
    api = stack.enter_context(agents(gateway_url=f"http://127.0.0.1:{TOOLS_PORT}"))
    created = api.post("/v1/workflows/definitions", json={"yaml": DEFINITION}, headers=TEAM)
    live = api.post("/v1/workflows/definitions/uc251_fee_dispute/publish-requests", json={}, headers=TEAM)
    check(
        "0 the fee dispute workflow saves and goes live",
        created.status_code == 201 and data(live)["status"] == "approved",
        created.text[:300],
    )
    stack.enter_context(engine_worker("uc251", {"OPS_GATEWAY_URL": f"http://127.0.0.1:{TOOLS_PORT}"}))

    started = api.post(
        "/v1/runs", json={"workflowId": "uc251_fee_dispute", "input": DISPUTE, "runKey": "uc251-a"}, headers=TEAM
    )
    run_id = str(data(started)["runId"])
    waiting = until(
        lambda: (r := data(api.get(f"/v1/runs/{run_id}", headers=TEAM)) or {}).get("status") == "waiting" and r
    )
    case = case_of(api, run_id)
    fields = [(f["key"], f["display"]) for f in case.get("typedFields") or []]
    check(
        "1 the case shows its fields in the complaint type's order, the amount as money",
        fields == [("complaint", DISPUTE["complaint"]), ("category", "fees"), ("urgency", ""), ("amount", "35.00")]
        and (case.get("caseType") or {}).get("id") == "complaint",
        {"fields": fields, "type": case.get("caseType"), "waiting": bool(waiting)},
    )
    tasks, actions = case.get("waiting") or [], case.get("actions") or []
    check(
        "2 it says what it waits on, the drafted action and where to decide it",
        len(tasks) == 1
        and (case.get("nextAction") or {}).get("href") == tasks[0]["href"]
        and len(actions) == 1
        and actions[0]["status"] == "pending"
        and actions[0]["href"] == tasks[0]["href"],
        {"waiting": tasks, "actions": actions, "next": case.get("nextAction")},
    )
    links = case.get("links") or {}
    check(
        "3 it links the run that opened it, its workflow and the dispute letter",
        [r["id"] for r in links.get("runs") or []] == [run_id]
        and (case.get("workflow") or {}).get("name") == "Fee dispute (uc-251)"
        and any(f["fileId"] == LETTER and f["name"] == "dispute-letter.pdf" for f in links.get("files") or []),
        {"links": links, "workflow": case.get("workflow")},
    )

    review_id = tasks[0]["taskId"] if tasks else run_id
    decided = api.post(
        f"/reviews/{review_id}/decision", json={"decision": "approved", "reason": "uc-251"}, headers=TEAM
    )
    after = until(lambda: (c := case_of(api, run_id)) and not c.get("waiting") and c) or {}
    done = [a for a in after.get("actions") or [] if a["taskId"] == review_id]
    lines = [a["text"] for a in (after.get("activity") or {}).get("recent") or []]
    check(
        "4 approved on its task page, the case reads the action decided and nothing waiting",
        decided.status_code == 200
        and after.get("waiting") == []
        and after.get("nextAction") is None
        and [a["status"] for a in done] == ["approved"],
        {"decision": decided.status_code, "actions": after.get("actions"), "waiting": after.get("waiting")},
    )
    listed = data(api.get(f"/v1/activity?case={after.get('id')}&kind=decision", headers=TEAM)) or {}
    check(
        "5 the decision is a line of the case's activity",
        (listed.get("pagination") or {}).get("total") == 1
        and after["activity"]["allHref"] == f"/activity?case={after['id']}",
        {"recent": lines, "decisions": listed.get("pagination")},
    )

finish()
