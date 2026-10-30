"""uc-588 evidence, run by hand and never in the nightly run: the bearer method against a real system, Stripe's API in
test mode. A Stripe plugin (a manifest only, written to a temporary folder because docs/ holds no Python packages)
signs in with a fixed token; a team turns it on with a Stripe test key, Test connection reads the balance, and a run's
call reads it again. The key comes from STRIPE_TEST_KEY, must be a test-mode key (sk_test_), and is never printed:
every answer and the tools-service log are searched for it.

    STRIPE_TEST_KEY=<a Stripe test-mode key from your secret store> \\
      PYTHONPATH=$PWD/docs/usecases/lib uv run --directory services/agents-service python \\
      ../../docs/usecases/tools-service/scripts/evidence-uc-588-stripe.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

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
    until,
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
egress: [api.stripe.com]
endpoint: "https://api.stripe.com/v1"
tools:
  - name: balance
    title: Read the balance
    access: read
    request: { method: GET, path: /balance }
"""
KEY = os.environ.get("STRIPE_TEST_KEY", "")
if not KEY.startswith("sk_test_"):
    sys.exit("FAIL set STRIPE_TEST_KEY to a Stripe test-mode key (sk_test_...); a live key is refused")
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}

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
    seen: list[str] = []

    api.put("/v1/policies/plugins", json={"value": {"evidence.stripe": {"enabled": True}}}, headers=sam)
    gw.post("/v1/egress/hosts", json={"value": "api.stripe.com", "note": "uc-588 evidence"}, headers=sam)
    until(lambda: all(p["installOn"] for p in (data(gw.get("/v1/plugins", headers=priya)) or {}).get("plugins", [])))
    on = gw.put(
        "/v1/plugins/evidence.stripe/team", json={"enabled": True, "credentials": {"token": KEY}}, headers=priya
    )
    seen.append(on.text)
    connection_id = str((data(on) or {}).get("connectionId") or "con_missing")
    tested = gw.post(f"/v1/connections/{connection_id}/test", json={"environment": "production"}, headers=priya)
    seen.append(tested.text)
    health = (data(tested) or {}).get("health") or {}
    headers = service_headers("tools", tenant=tenant, service="agents", team="team_ops")
    body = {"tool": "stripe_balance", "input": {}, "key": uuid4().hex, "runContext": {"environment": "production"}}
    called = gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"})
    seen.append(called.text)
    out = (data(called) or {}).get("output") or {}
    check(
        "S1 evidence: a team turns on a bearer plugin for Stripe with a test key; Test connection and a run's call "
        "read the test-mode balance",
        on.status_code == 200
        and health.get("status") == "ok"
        and out.get("object") == "balance"
        and out.get("livemode") is False,
        {"health": health, "object": out.get("object"), "livemode": out.get("livemode")},
    )
    logs = "".join(p.read_text(errors="replace") for p in LOG_DIR.glob(f"tools-{TOOLS_PORT}.log"))
    check(
        "S5 evidence: the Stripe key appears in no answer and no tools-service log line",
        not any(KEY in t for t in [*seen, logs]),
    )

finish()
