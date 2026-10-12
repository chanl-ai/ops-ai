"""uc-007 a tool write without a token is refused, api layer: docs/usecases/tools-service/write-without-token-refused.md."""

from __future__ import annotations

import time

from ops_tools.tokens import Binding, mint
from ops_service_kit.ids import input_hash

from usecase_harness import check, finish, service_headers, tools

DOC = {"customerId": "C-1042", "document": "proof of address", "reason": "Address changed last week."}
THREAD = f"uc007_{int(time.time())}"
# The dev review key from the settings defaults; the review service signs with it, and the gateway hands it to OPA.
REVIEW_KEY = "dev-review-key-not-secret"


def call(c, step: str, token: str | None):  # type: ignore[no-untyped-def]
    return c.post(
        "/v1/calls",
        headers=service_headers("tools"),
        json={
            "tool": "request_document",
            "input": DOC,
            "key": step,
            "runContext": {"thread": THREAD, "step": step, "act": "usecase"},
            "approvalToken": token,
        },
    )


with tools() as gw:
    refused = call(gw, "s1", None)
    reasons = refused.json().get("error", {}).get("details", {}).get("reasons") if refused.status_code != 200 else None
    check("write without a token is refused (403)", refused.status_code == 403, refused.text[:200])
    check("refusal names the missing approval token", reasons == ["write needs an approval token"], reasons)
    # Non-vacuous: the same write with a valid token must run, so the 403 above is the policy and not a dead gateway.
    token = mint(
        Binding(THREAD, "s2", "request_document", input_hash(DOC), ["reviewer@bank.test"]), REVIEW_KEY, ttl_s=300
    )
    allowed = call(gw, "s2", token)
    check("same write with an approval token runs (200)", allowed.status_code == 200, allowed.text[:200])
    output = allowed.json().get("data", {}).get("output", {}) if allowed.status_code == 200 else {}
    check("tool output says completed", output.get("status") == "completed", output)

finish()
