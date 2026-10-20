"""Who may change a tool module and who may decide its approvals (c-080), through the real routes with people signed in
on platform-style tokens. Building needs builder or admin in the team acting; approving needs approver or admin. A
viewer who could publish a module would change what every agent may call, and a builder who could approve access would
grant it to their own workflows."""

from __future__ import annotations

import httpx

from .test_egress_and_secrets_need_security_admin import client  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .test_review_decisions import person

MODULES = "/v1/tool-modules"
ACCESS = {
    "workflowId": "wf_wire",
    "environment": "production",
    "operations": ["get_customer_profile"],
    "expiresInDays": 90,
    "justification": "Wire reviews need the customer's profile",
}


def _refused(r: httpx.Response) -> None:
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text


async def test_only_a_builder_or_admin_changes_a_module(client: httpx.AsyncClient, tenant: str) -> None:  # noqa: F811
    viewer = person(tenant, "Vic Moreno", {"team_platform": "viewer"})
    approver = person(tenant, "Maya Okafor", {"team_platform": "approver"})
    builder = person(tenant, "James Richardson", {"team_platform": "builder"})
    blank = {"displayName": "Ledger", "name": "ledger", "type": "http"}
    for who in (viewer, approver):
        _refused(await client.post(f"{MODULES}/blank", json=blank, headers=who))
        _refused(await client.patch(f"{MODULES}/mod_core_banking", json={"description": "x"}, headers=who))
        _refused(await client.post(f"{MODULES}/mod_core_banking/versions", json={"note": "x"}, headers=who))
        _refused(await client.delete(f"{MODULES}/mod_core_banking", headers=who))
    assert (await client.post(f"{MODULES}/blank", json=blank, headers=builder)).status_code == 201
    # Reading stays open to the team.
    assert (await client.get(f"{MODULES}/mod_core_banking", headers=viewer)).status_code == 200


async def test_a_module_approval_is_decided_in_human_tasks_not_on_the_module(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
) -> None:
    # c-166/c-257: who decides is can(reviews.decide) on the request's workflow run (agents-service's tests); here, no
    # person decides it, an approver included (test_apply_tool_access covers the run's apply). Revoking stays here.
    james = person(tenant, "James Richardson", {"team_platform": "builder"})
    bob = person(tenant, "Bob Tanaka", {"team_platform": "builder"})
    maya = person(tenant, "Maya Okafor", {"team_platform": "approver"})
    r = await client.post(f"{MODULES}/mod_core_banking/approvals", json=ACCESS, headers=james)
    assert r.status_code == 201 and r.json()["data"]["reviewId"], r.text
    decide = f"{MODULES}/mod_core_banking/approvals/{r.json()['data']['id']}/decide"
    on_module = await client.post(decide, json={"decision": "approved"}, headers=maya)
    assert (on_module.status_code, on_module.json()["error"]["code"]) == (409, "decided_in_reviews"), on_module.text
    revoke = {"ids": [r.json()["data"]["id"]], "reason": "not needed"}
    _refused(await client.post(f"{MODULES}/mod_core_banking/approvals/revoke", json=revoke, headers=bob))
