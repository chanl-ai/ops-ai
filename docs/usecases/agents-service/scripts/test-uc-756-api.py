"""uc-756, api layer: docs/usecases/agents-service/a-shared-form-filled-in-signed.md. A builder shares a workflow as a form;
a signed-out person fills it in; the run reads the account, searches the knowledge source, waits for a person to approve the
hold, places it on the mock bank once and finishes with a case. Platform sign-in, a workflow worker, no model call."""

from __future__ import annotations

import secrets
import time
from typing import Any

import httpx
from main_chains import ACCOUNT, bank_stack, holds, publish_bank_module
from usecase_harness import check, data, finish, until

RUN = int(time.time())
WF = f"uc756_form_{RUN}"
FORM_SCHEMA = {
    "type": "object",
    "title": "Hold my account",
    "required": ["accountId", "question"],
    "properties": {
        "accountId": {"type": "string", "title": "Account number"},
        "question": {"type": "string", "title": "What do you need to know first"},
    },
}


def definition(read: str, write: str) -> dict[str, Any]:
    def node(nid: str, kind: str, **params: Any) -> dict[str, Any]:
        return {"id": nid, "type": kind, "typeVersion": 1, "name": nid.capitalize(), "parameters": params}

    return {
        "schemaVersion": 2,
        "id": WF,
        "name": f"Hold an account {RUN}",
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Form", "parameters": {"inputSchema": FORM_SCHEMA}},
            node("read", "ops.action.tool", operation=read, input={"accountId": "$.input.accountId"}),
            node("search", "ops.ai.knowledge", query="$.input.question", kbIds=["kb_people"], limit=3),
            node("review", "ops.flow.humanReview", title="Hold {$.input.accountId}?", approves="freeze"),
            node("freeze", "ops.action.tool", operation=write, approvedBy="review", input={"accountId": "$.input.accountId"}),
            node("open", "ops.action.openCase", subject="Hold on {$.input.accountId}", priority="normal", caseType="complaint", fields={"complaint": "$.input.question"}),
            node("done", "ops.flow.end", outcome="held"),
            node("declined", "ops.flow.end", outcome="declined"),
            node("failed", "ops.flow.end", outcome="failed", result="failed"),
        ],
        "connections": [
            {"from": {"node": "start", "port": "payload"}, "to": {"node": "read", "port": "in"}},
            {"from": {"node": "read", "port": "ok"}, "to": {"node": "search", "port": "in"}},
            {"from": {"node": "read", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "read", "port": "refused"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "search", "port": "found"}, "to": {"node": "review", "port": "in"}},
            {"from": {"node": "search", "port": "notFound"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "review", "port": "approve"}, "to": {"node": "freeze", "port": "in"}},
            {"from": {"node": "review", "port": "reject"}, "to": {"node": "declined", "port": "in"}},
            {"from": {"node": "freeze", "port": "ok"}, "to": {"node": "open", "port": "in"}},
            {"from": {"node": "freeze", "port": "refused"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "freeze", "port": "error"}, "to": {"node": "failed", "port": "in"}},
            {"from": {"node": "open", "port": "opened"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "open", "port": "error"}, "to": {"node": "failed", "port": "in"}},
        ],
    }


with bank_stack(worker="uc756") as s:
    builder, approver, security = s.who["builder"], s.who["approver"], s.who["security"]
    module, read, write = publish_bank_module(s.gw, RUN, approval=True, team=builder, security=security)
    time.sleep(31)  # agents-service keeps each tenant's tool list for 30 seconds
    saved = s.api.post("/v1/workflows/definitions", json={"definition": definition(read, write)}, headers=builder)
    asked = s.api.post(f"/v1/workflows/definitions/{WF}/publish-requests", json={}, headers=builder)
    status = str((data(asked) or {}).get("status"))
    if status == "pending":
        decided = s.api.post(f"/v1/publish-requests/{(data(asked) or {}).get('id')}/decision", json={"decision": "approved"}, headers=approver)
        status = str((data(decided) or {}).get("status"))
    check("0 the workflow saves and goes live", saved.status_code in (200, 201) and status == "approved", (saved.text[:300], asked.text[:300], status))

    if status != "approved":
        finish()
        raise SystemExit(1)

    shared = s.api.post(
        f"/v1/workflows/{WF}/forms",
        json={"mode": "link", "expiresInDays": 7, "dailyCap": 20, "title": "Hold my account", "description": "We place the hold after a person approves it.", "afterText": "Thanks, we have your request."},
        headers=builder,
    )
    form = data(shared) or {}
    slug, token = str(form.get("slug")), str(form.get("token"))
    check("1 the builder shares the workflow as a form with a link", shared.status_code == 201 and bool(slug and token), shared.text[:300])

    # Signed out: a client with no token and no team header, which is how a bank customer reaches the link.
    with httpx.Client(base_url=str(s.api.base_url), timeout=30) as visitor:
        page = visitor.get(f"/v1/forms/public/{slug}", params={"t": token})
        wrong = visitor.post(f"/v1/forms/public/{slug}/submit", params={"t": "not-the-token"}, json={"values": {"accountId": ACCOUNT, "question": "daily wire limit"}})
        check("2 the link opens signed out, and a wrong token is refused", page.status_code == 200 and wrong.status_code in (401, 403, 404), (page.status_code, wrong.status_code))
        sent = visitor.post(
            f"/v1/forms/public/{slug}/submit",
            params={"t": token},
            json={"values": {"accountId": ACCOUNT, "question": "What is the daily wire limit for a personal account?"}},
            headers={"X-Forwarded-For": f"203.0.113.{secrets.randbelow(200) + 1}"},
        )
    check("3 the signed-out submission is received", sent.status_code in (201, 202), (sent.status_code, sent.text[:200]))

    def started() -> dict[str, Any] | None:
        rows = (data(s.api.get("/v1/runs", params={"workflowId": WF, "pageSize": 20}, headers=builder)) or {}).get("data") or []
        return next((r for r in rows if r.get("createdBy") == f"trigger:form:{form.get('id')}"), None)

    run = until(started, timeout=60) or {}
    check("4 the form started a run in the team, created by the form", bool(run), sent.text[:200])
    run_id = str(run.get("id", "run_x"))

    def detail() -> dict[str, Any]:
        return data(s.api.get(f"/v1/runs/{run_id}", headers=builder)) or {}

    waiting = until(lambda: (d := detail()).get("status") == "waiting" and d, timeout=90) or {}
    steps = {st.get("nodeId"): st for st in waiting.get("steps") or []}
    cited = (steps.get("search") or {}).get("output") or {}
    check("5 the run read the account and the knowledge source, then waits for a person", bool(waiting) and bool(steps.get("read")) and bool(cited), {k: str(v)[:160] for k, v in steps.items()})
    # Non-vacuous: the write has not run while the review waits, so the one hold below is the approval's doing.
    check("6 no hold has reached the bank while the review waits", not holds(s.bank), holds(s.bank))

    review_id = f"{run_id}:review:{(steps.get('review') or {}).get('iteration', 1)}"
    mine = s.api.post(f"/reviews/{review_id}/decision", json={"decision": "approve"}, headers=approver)
    check("7 a person of the team approves the hold", mine.status_code == 200, (review_id, mine.status_code, mine.text[:300]))
    done = until(lambda: (d := detail()).get("status") in ("succeeded", "failed", "cancelled") and d, timeout=90) or {}
    opened = next((st for st in done.get("steps") or [] if st.get("nodeId") == "open"), {})
    case_id = (opened.get("output") or {}).get("caseId")
    case = data(s.api.get(f"/v1/cases/{case_id}", headers=builder)) if case_id else {}
    check("8 the hold runs once, and the run finishes held with a case", len(holds(s.bank)) == 1 and done.get("outcome") == "held" and bool((case or {}).get("id")), (len(holds(s.bank)), done.get("status"), done.get("outcome"), str(case)[:160]))
finish()
