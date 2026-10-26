"""uc-010 a builder manages a tool module, api layer: docs/usecases/tools-service/manage-tool-modules.md."""

from __future__ import annotations

import time
from typing import Any

from fake_bank_https import HOST, fake_bank
from usecase_harness import AGENTS_PORT, agents, approve_tool_review, check, data, finish, service_headers, tools

OTHER = {"X-Dev-User": "Priya Shah"}
SECURITY = {"X-Dev-User": "Nadia Petrov", "X-Team-Id": "team_security"}
RUN = int(time.time())
OPERATION = {
    "name": f"get_statement_{RUN}",
    "description": "Monthly statement for an account",
    "access": "read",
    "method": "GET",
    "url": f"https://statements-{RUN}.harborpine.internal/v1/accounts/{{accountId}}/statement",
    "headers": [{"key": "Authorization", "value": "Bearer sk_live_9f2c"}],
}
APPROVAL = {
    "workflowId": "dispute_email",  # an agents-service workflow (c-039): tools-service reads them from there
    "environment": "production",
    "operations": ["get_customer_profile"],
    "expiresInDays": 90,
    "justification": "Wire reviews read the customer's profile",
}


def detail(gw: Any, module_id: str) -> dict[str, Any]:
    return data(gw.get(f"/v1/tool-modules/{module_id}"))


with agents(), tools(settings={"OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}"}) as gw:
    # A fresh name per run, so a run on a kept database (an explicit OPS_USECASE_DB) does not meet the last one's
    # module.
    name = f"statements-{RUN}"
    blank = gw.post("/v1/tool-modules/blank", json={"displayName": "Statements", "name": name, "type": "http"})
    check("a blank module is saved as a draft (201)", blank.status_code == 201, blank.text[:200])
    module_id = data(blank)["id"] if blank.status_code == 201 else ""

    literal = gw.post(f"/v1/tool-modules/{module_id}/operations", json=OPERATION)
    check("a literal credential in a header is refused (400)", literal.status_code == 400, literal.text[:200])
    referenced = {**OPERATION, "headers": [{"key": "Authorization", "value": "{{STATEMENTS_TOKEN}}"}]}
    unlisted = gw.post(f"/v1/tool-modules/{module_id}/operations", json=referenced)
    check(
        "an operation on a host off the egress allow-list is refused (422)",
        unlisted.status_code == 422,
        unlisted.text[:200],
    )
    gw.post("/v1/egress/hosts", json={"value": f"statements-{RUN}.harborpine.internal", "note": "statements"})
    added = gw.post(f"/v1/tool-modules/{module_id}/operations", json=referenced)
    ops = [o["name"] for o in data(added)["operations"]] if added.status_code == 200 else []
    check("the operation is added with a vault reference instead", ops == [OPERATION["name"]], added.text[:200])

    review = gw.post(f"/v1/tool-modules/{module_id}/reviews", json={"note": "First version"})
    check(
        "requesting a security review moves the draft to review",
        data(review).get("status") == "in_review",
        review.text[:200],
    )

    core = detail(gw, "mod_core_banking")
    read = next(o for o in core["operations"] if o["name"] == "get_loan_account")
    limit = {"rateLimitPerMin": read["rateLimitPerMin"] + 1}
    gw.patch(f"/v1/tool-modules/mod_core_banking/operations/{read['id']}", json=limit)
    published = gw.post("/v1/tool-modules/mod_core_banking/versions", json={"note": "Higher read limit"})
    major, minor, _ = core["version"].split(".")
    expected = f"{major}.{int(minor) + 1}.0"
    check(
        "a minor change publishes the next minor version",
        data(published).get("version") == expected,
        published.text[:200],
    )

    requested = gw.post("/v1/tool-modules/mod_core_banking/approvals", json=APPROVAL)
    check("a workflow approval is requested (201)", requested.status_code == 201, requested.text[:200])
    approval_id = data(requested)["id"] if requested.status_code == 201 else ""
    # Decided by its system workflow run (c-257): the request names the run's key, and the module page decides nothing.
    # The decision itself, through Human Tasks, the worker and the gateway, is uc-053's.
    review_id = data(requested)["reviewId"] if requested.status_code == 201 else ""
    check("the request names its workflow run", review_id == f"tool_access.requested:{approval_id}", review_id)
    decide_on_module = f"/v1/tool-modules/mod_core_banking/approvals/{approval_id}/decide"
    on_module = gw.post(decide_on_module, json={"decision": "approved"}, headers=OTHER)
    check("the module page no longer decides it (409)", on_module.status_code == 409, on_module.text[:200])

with agents(), tools() as gw:
    again = detail(gw, module_id)
    check(
        "the draft and its operation survive a restart",
        [o["name"] for o in again.get("operations", [])] == [OPERATION["name"]],
        again,
    )
    approvals = [a for a in detail(gw, "mod_core_banking")["approvals"] if a["id"] == approval_id]
    check("the open request survives a restart", [a["status"] for a in approvals] == ["requested"], approvals)


# c-027: an operation's HTTP call edited after it is added, called through the gateway against the fake bank.
TOOL = f"bank_account_{RUN}"


def publish(gw: Any, module_id: str) -> dict[str, Any]:
    """Publishes what is staged; a major version is approved by Security so it serves."""
    out = data(gw.post(f"/v1/tool-modules/{module_id}/versions", json={"note": "c-027"}))
    if any(v["status"] == "in_review" for v in out["versions"]):
        out = approve_tool_review(gw, module_id, SECURITY)
    return out


def call(gw: Any, step: str) -> dict[str, Any]:
    body = {
        "tool": TOOL,
        "input": {"accountId": "CHQ-2219"},
        "key": f"{TOOL}-{step}",
        "runContext": {"thread": f"gth_uc010_{RUN}", "step": step, "act": "agent:uc010"},
    }
    r = gw.post("/v1/calls", json=body, headers=service_headers("tools"))
    return {"status": r.status_code, "text": r.text[:300], **(r.json().get("data") or {})}


def patch(gw: Any, module_id: str, op_id: str, body: dict[str, Any]) -> Any:
    return gw.patch(f"/v1/tool-modules/{module_id}/operations/{op_id}", json=body)


with fake_bank() as bank, agents(), tools(settings=bank.settings) as gw:
    gw.post("/v1/egress/hosts", json={"value": HOST, "note": "uc-010 fake bank"})
    gw.post("/v1/egress/ranges", json={"value": bank.range, "note": "uc-010 fake bank network"})
    made = data(gw.post("/v1/tool-modules/blank", json={"displayName": "Bank", "name": f"bank-{RUN}", "type": "http"}))
    bank_id = made["id"]
    op = {
        "name": TOOL,
        "description": "An account",
        "access": "read",
        "method": "GET",
        "url": f"https://{HOST}/v1/accounts/{{accountId}}",
    }
    first = data(gw.post(f"/v1/tool-modules/{bank_id}/operations", json=op))
    op_id = first["operations"][0]["id"]
    data(gw.post(f"/v1/tool-modules/{bank_id}/reviews", json={"note": "uc-010"}))
    start = approve_tool_review(gw, bank_id, SECURITY)
    check("the bank operation runs once published", call(gw, "a").get("output", {}).get("accountId") == "CHQ-2219")

    foreign = patch(gw, bank_id, op_id, {"path": "https://other.bank.test/v1/x"})
    literal = patch(gw, bank_id, op_id, {"headers": [{"key": "X-Api-Key", "value": "sk_live_123"}]})
    check(
        "an edit off the module endpoint (400) or with a literal credential (400) is refused",
        foreign.status_code == 400 and literal.status_code == 400,
        [foreign.text[:120], literal.text[:120]],
    )
    patch(
        gw,
        bank_id,
        op_id,
        {"path": "/v1/statements/latest", "headers": [{"key": "X-Api-Key", "value": "{{UC010_KEY}}"}]},
    )
    pending = call(gw, "b")
    check(
        "while the edit is pending, calls run the published call",
        pending.get("output", {}).get("accountId") == "CHQ-2219",
        pending,
    )
    after = publish(gw, bank_id)
    major_up = f"{int(start['version'].split('.')[0]) + 1}.0.0"
    check("a path edit publishes the next major version", after.get("version") == major_up, after.get("version"))
    patch(gw, bank_id, op_id, {"path": "/v1/accounts/{accountId}", "headers": []})
    publish(gw, bank_id)

    patch(gw, bank_id, op_id, {"responseTransform": '{"id": "{{ data.accountId }}"}'})
    publish(gw, bank_id)
    check("a response transform shapes what the agent gets", call(gw, "c").get("output") == {"id": "CHQ-2219"})
    patch(gw, bank_id, op_id, {"responseTransform": "{{ data.missing.field }}"})
    publish(gw, bank_id)
    broken = call(gw, "d")
    check(
        "a transform that fails returns the answer and the error, not a 500",
        broken["status"] == 200
        and broken.get("ok") is True
        and "transform_error" in broken.get("output", {})
        and broken["output"]["response"]["accountId"] == "CHQ-2219",
        broken,
    )

    patch(gw, bank_id, op_id, {"path": "/v1/slow", "responseTransform": None, "timeoutMs": 1000})
    publish(gw, bank_id)
    slow = call(gw, "e")
    rows = data(gw.get("/v1/executions", params={"tool": TOOL}))["data"]
    err = slow.get("output", {}).get("error", {})
    check(
        "an operation's own timeout stops the call with UPSTREAM_TIMEOUT, logged",
        err.get("code") == "UPSTREAM_TIMEOUT" and "1000 ms" in err.get("message", "") and rows[0]["status"] == "error",
        [slow.get("output"), rows[0]["status"] if rows else None],
    )
    edited = detail(gw, bank_id)["operations"][0]

with agents(), tools() as gw:
    kept = detail(gw, bank_id)["operations"][0]
    check(
        "the edited call survives a restart",
        (kept["path"], kept.get("timeoutMs")) == ("/v1/slow", 1000) == (edited["path"], edited.get("timeoutMs")),
        kept,
    )

finish()
