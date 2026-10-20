"""uc-218 a person invited as a reviewer decides a builder's publish request and edits no agent, api layer:
docs/usecases/platform-service/role-reviewer.md."""

from __future__ import annotations

import secrets

from usecase_harness import bearer, check, data, finish, invited, people_stack, signed_in

PRIYA = "p.shah@northfieldbank.com"

with people_stack(agents_env={"OPS_REGISTRY_AUTO_APPROVE": "false"}) as (api, agents):
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    builder = bearer(invited(api, priya, f"b.{secrets.token_hex(3)}@northfieldbank.com", "builder"), "team_ops")
    reviewer = bearer(invited(api, priya, f"r.{secrets.token_hex(3)}@northfieldbank.com", "approver"), "team_ops")

    agent = data(
        agents.post("/v1/agents", json={"name": f"Desk {secrets.token_hex(2)}", "role": "Answers"}, headers=builder)
    )
    r = agents.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": agent["version"]}, headers=builder)
    request = data(r) if r.status_code in (200, 201) else {}
    check("a builder's publish request waits for review", request.get("status") == "pending", r.text[:200])
    r = agents.post(
        f"/v1/publish-requests/{request.get('id', 'pr_x')}/decision", json={"decision": "approved"}, headers=reviewer
    )
    check(
        "the reviewer approves it",
        r.status_code == 200 and data(r).get("status") == "approved",
        r.text[:200],
    )
    r = agents.post("/v1/agents", json={"name": "Reviewer's agent", "role": "Answers"}, headers=reviewer)
    check("the reviewer cannot create an agent (403)", r.status_code == 403, r.text[:200])
    r = agents.patch(f"/v1/agents/{agent['id']}", json={"role": "Changed by a reviewer"}, headers=reviewer)
    check("the reviewer cannot edit the agent they approved (403)", r.status_code == 403, r.text[:200])

finish()
