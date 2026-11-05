"""uc-584 evidence, run by hand and never in the nightly run: a header, a form body and an amount limit against a real
system, Stripe's API in test mode. A Stripe plugin (a manifest only, written to a temporary folder because docs/ holds
no Python packages) sends `Stripe-Version` from a setting on every request, creates a customer with a form body (Stripe
refuses JSON), and creates a payment intent under an `amount_max`. A payment intent over the limit never leaves, and a
version Stripe does not know is refused by Stripe, which shows the header arrives. The key comes from STRIPE_TEST_KEY,
must be a test-mode key (sk_test_), and is never printed: every answer and the tools-service log are searched for it.

    STRIPE_TEST_KEY=<a Stripe test-mode key from your secret store> \\
      PYTHONPATH=$PWD/docs/usecases/lib uv run --directory services/agents-service python \\
      ../../docs/usecases/tools-service/scripts/evidence-uc-584-stripe.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from usecase_harness import (
    LOG_DIR,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    TOOLS_PORT,
    bearer,
    check,
    data,
    finish,
    platform,
    service_headers,
    signed_in,
    tools,
)

MANIFEST = """\
schema: ops-ai/plugin@2
id: evidence.stripe
title: Stripe (test mode)
version: 0.1.0
sdk: "1"
connection:
  kinds: [bearer]
  sign_in: [team]
  health_check: { path: "/v1/balance" }
settings:
  stripe_version: { type: string, title: API version, default: "2024-06-20" }
egress: [api.stripe.com]
endpoint: "https://api.stripe.com/v1"
headers: { Stripe-Version: "{stripe_version}" }
tools:
  - name: create_customer
    title: Create a customer
    access: write
    requires_approval: false
    input: { name: { type: string }, email: { type: string } }
    request: { method: POST, path: /customers, form: { name: "{{name}}", email: "{{email}}" } }
  - name: create_payment
    title: Take a payment
    access: write
    requires_approval: false
    input: { amount: { type: integer }, currency: { type: string, enum: [usd, eur, gbp] } }
    amount_max: 5000
    request:
      method: POST
      path: /payment_intents
      form: { amount: "{{amount}}", currency: "{{currency}}", "payment_method_types[]": card }
"""
KEY = os.environ.get("STRIPE_TEST_KEY", "")
if not KEY.startswith("sk_test_"):
    sys.exit("FAIL set STRIPE_TEST_KEY to a Stripe test-mode key (sk_test_...); a live key is refused")
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
SEEN: list[str] = []


def kept(r: httpx.Response) -> httpx.Response:
    SEEN.append(r.text)
    return r


with ExitStack() as stack:
    folder = Path(stack.enter_context(tempfile.TemporaryDirectory())) / "evidence_stripe"
    folder.mkdir()
    (folder / "plugin.yaml").write_text(MANIFEST)
    (folder / "__init__.py").write_text("from ops_plugin_sdk import Plugin\n\nplugin = Plugin.beside(__file__)\n")
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(folder)])}
    api, _ = stack.enter_context(platform())
    gw = stack.enter_context(tools({**AUTH, **plugins}))
    sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
    session = signed_in(api, "p.shah@harborpine.example")
    priya = bearer(session, "team_ops")
    tenant = str((session.get("principal") or {}).get("tenantId") or session.get("tenantId") or "")

    def call(tool: str, args: dict[str, Any]) -> httpx.Response:
        headers = service_headers("tools", tenant=tenant, service="agents", team="team_ops")
        body = {"tool": tool, "input": args, "key": uuid4().hex, "runContext": {"environment": "live"}}
        return kept(gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"}))

    def output(r: httpx.Response) -> dict[str, Any]:
        return dict((data(r) or {}).get("output") or {}) if r.status_code == 200 else {}

    gw.post("/v1/egress/hosts", json={"value": "api.stripe.com", "note": "uc-584 evidence"}, headers=sam)
    on = kept(
        gw.put(
            "/v1/apps/plugin:evidence.stripe/team", json={"enabled": True, "credentials": {"token": KEY}}, headers=priya
        )
    )

    customer = call("stripe_create_customer", {"name": "Harbor test customer", "email": "test@harborpine.example"})
    check(
        "S2 evidence: a form body creates a Stripe test-mode customer (Stripe refuses JSON bodies)",
        on.status_code == 200 and output(customer).get("object") == "customer"
        and output(customer).get("livemode") is False and output(customer).get("name") == "Harbor test customer",
        {"on": on.status_code, "object": output(customer).get("object"), "error": customer.text[:300]},
    )  # fmt: skip

    within = call("stripe_create_payment", {"amount": 1500, "currency": "usd"})
    over = call("stripe_create_payment", {"amount": 9900, "currency": "usd"})
    over_error = ((data(over) or {}).get("output") or {}).get("error") or over.json().get("error") or {}
    check(
        "S2 evidence: a payment intent of 1500 under the limit of 5000 is created in test mode; one of 9900 is "
        "refused amount_over_limit before it leaves",
        output(within).get("object") == "payment_intent" and output(within).get("amount") == 1500
        and output(within).get("livemode") is False and over_error.get("code") == "amount_over_limit",
        {"within": output(within).get("object"), "over": over_error, "error": within.text[:300]},
    )  # fmt: skip

    kept(
        gw.put(
            "/v1/apps/plugin:evidence.stripe/team",
            json={"enabled": True, "settings": {"stripe_version": "1999-01-01"}},
            headers=priya,
        )
    )
    old = call("stripe_create_customer", {"name": "Never created", "email": "never@harborpine.example"})
    old_error = ((data(old) or {}).get("output") or {}).get("error") or {}
    check(
        "S1 evidence: with the plugin's Stripe-Version set to a version Stripe does not know, Stripe refuses the call",
        old_error.get("status") == 400,
        old_error,
    )

    logs = "".join(p.read_text(errors="replace") for p in LOG_DIR.glob(f"tools-{TOOLS_PORT}.log"))
    check(
        "S1 evidence: the Stripe key appears in no answer and no tools-service log line",
        not any(KEY in t for t in [*SEEN, logs]),
    )

finish()
