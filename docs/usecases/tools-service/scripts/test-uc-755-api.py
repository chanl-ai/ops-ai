"""uc-755, api layer: docs/usecases/tools-service/a-team-holding-only-a-workflow.md. The Platform-style owner (team_ops)
publishes a bank module and approves a workflow of a second team ("Desk", made on the Teams page) to call its read. A
plain builder of Desk, added by invite-and-accept and not the team's creator, sees the module and is refused 404 on every
edit, publish, run outside the workflow, revoke and delete; the module's can* flags are off; the owner's copy is
unchanged. Platform sign-in (lib/main_chains.py bank_stack), no model call."""

from __future__ import annotations

import json
import secrets
import time

from main_chains import bank_stack, publish_bank_module
from usecase_harness import INVITED_PASSWORD, as_role, bearer, check, data, finish, invited, signed_in

RUN = int(time.time())
WANJIRU = "w.kamau@harborpine.example"
PRIYA = "p.shah@harborpine.example"

with bank_stack() as s:
    owner, security = s.who["builder"], s.who["security"]
    module, read, _write = publish_bank_module(s.gw, RUN, approval=False, team=owner, security=security)
    base = f"/v1/tool-modules/{module}"

    wanjiru = signed_in(s.accounts, WANJIRU)
    made = s.accounts.post("/v1/settings/teams", json={"name": f"Desk {secrets.token_hex(2)}", "admin": PRIYA}, headers=bearer(wanjiru, "team_platform"))
    desk = str((data(made) or {}).get("id", "team_x"))
    check("setup: a second team is made on the Teams page", made.status_code == 201, made.text[:200])
    # Making a team changes permissions, which refuses tokens issued before it: the seeded people sign in again.
    s.who.update({role: as_role(s.accounts, role) for role in ("builder", "approver", "security")})
    owner, security = s.who["builder"], s.who["security"]
    # The member is invited by the workspace admin acting in Desk and signs in with the password they chose.
    email = f"desk.{secrets.token_hex(3)}@harborpine.example"
    priya = signed_in(s.accounts, PRIYA)
    invited(s.accounts, bearer(priya, desk), email, "builder")
    member = bearer(signed_in(s.accounts, email, INVITED_PASSWORD), desk)

    made_wf = s.api.post("/v1/workflows", json={"name": f"Desk intake {RUN}", "trigger": "manual"}, headers=member)
    check("setup: the Desk member makes a workflow of Desk's", made_wf.status_code in (200, 201), made_wf.text[:200])
    workflow = str((data(made_wf) or {}).get("id", "wf_x"))
    time.sleep(31)  # past the workflow list's 30 s cache, so tools-service sees the new workflow
    asked = s.gw.post(
        f"{base}/approvals",
        json={"workflowId": workflow, "environment": "production", "operations": [read], "expiresInDays": 30, "justification": "Desk intake reads accounts"},
        headers=owner,
    )
    grant = str((data(asked) or {}).get("id", "apr_x"))
    decided = s.gw.post(f"{base}/approvals/{grant}/decide", json={"decision": "approved"}, headers=s.who["approver"])
    check("setup: the owner's approver approves Desk's workflow for the read", asked.status_code == 201 and decided.status_code == 200, (asked.text[:200], decided.text[:200]))

    seen = s.gw.get(base, headers=member)
    detail = data(seen) or {}
    # Non-vacuous: the grant is real, so the member reads the module; the refusals below are the grant's limit, not a hidden module.
    check("1 Desk's builder reads the module through the grant, with every can flag off", seen.status_code == 200 and not any(detail.get(k) for k in ("canEdit", "canDelete", "canPublish")), (seen.status_code, {k: detail.get(k) for k in ("canEdit", "canDelete", "canPublish")}))

    held = data(s.gw.get(base, headers=owner)) or {}
    op = next((o for o in detail.get("operations", []) if o["name"] == read), {"id": "op_x"})
    http = {"name": "drain", "description": "d", "access": "read", "method": "GET", "url": "https://core.example/x"}
    tries = (
        ("edit the module", "PATCH", base, {"description": "changed by Desk"}),
        ("add an operation", "POST", f"{base}/operations", http),
        ("edit an operation", "PATCH", f"{base}/operations/{op['id']}", {"description": "changed by Desk"}),
        ("publish a version", "POST", f"{base}/versions", {"note": "Desk's release"}),
        ("ask for a review", "POST", f"{base}/reviews", {"note": "Desk asks"}),
        ("run it outside the workflow", "POST", f"{base}/operations/{read}/run", {"mode": "mock", "input": {}}),
        ("test it outside the workflow", "POST", f"{base}/test", {"operation": read, "contextId": "owner", "target": "stub", "input": {}}),
        ("revoke the grant", "POST", f"{base}/approvals/revoke", {"ids": [grant], "reason": "Desk ends it"}),
        ("decide the grant", "POST", f"{base}/approvals/{grant}/decide", {"decision": "rejected"}),
        ("delete the module", "DELETE", base, None),
    )
    for step, (what, method, path, body) in enumerate(tries, start=2):
        r = s.gw.request(method, path, json=body, headers=member)
        check(f"{step} Desk's builder cannot {what} (404)", r.status_code == 404, (r.status_code, r.text[:160]))
    bulk = s.gw.post("/v1/tool-modules/bulk-delete", json={"ids": [module]}, headers=member)
    check("12 a bulk delete skips the module as not found", data(bulk) == {"updated": [], "skipped": [{"id": module, "reason": "Not found"}]}, bulk.text[:200])

    after = data(s.gw.get(base, headers=owner)) or {}
    approvals = [a for a in after.get("approvals", []) if a.get("id") == grant]
    same = after.get("description") == held.get("description") and after.get("operations") == held.get("operations") and after.get("version") == held.get("version")
    check("13 the owner's module is unchanged and the grant still stands", same and bool(approvals) and approvals[0].get("status") == "approved", json.dumps(approvals)[:200])
finish()
