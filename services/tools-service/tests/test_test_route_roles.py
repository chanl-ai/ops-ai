"""Who may run a tool module's test (c-115): the workbench and the operation sheet both call POST
/v1/tool-modules/{id}/test, which makes a real read on the sandbox target. A builder or admin in the team acting runs
it; a viewer or reviewer gets 403 role_required, so a hidden button is never the only guard."""

from __future__ import annotations

from typing import Any

import httpx

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person

TEST = "/v1/tool-modules/mod_core_banking/test"
# No customer typed: the subject binding stays empty, so the answer carries no `sample` source, which the response
# schema does not list yet (a contract defect outside this card).
BODY: dict[str, Any] = {"operation": "get_customer_profile", "contextId": "owner", "target": "stub", "input": {}}


async def test_only_a_builder_or_admin_runs_a_module_test(client: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    for role in ("viewer", "approver"):
        who = person(tenant, f"Someone {role}", {"team_platform": role})
        r = await client.post(TEST, json=BODY, headers=who)
        assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text
    # The control: the same body from a builder runs the test and gets the gateway's decision.
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    r = await client.post(TEST, json=BODY, headers=builder)
    assert r.status_code == 200 and "decision" in r.json()["data"], r.text
