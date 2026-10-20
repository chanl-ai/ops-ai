"""uc-217 a person invited as a builder builds the team's agents and asks to publish, and decides nothing, api layer:
docs/usecases/platform-service/role-builder.md."""

from __future__ import annotations

import secrets

from usecase_harness import bearer, check, data, finish, invited, people_stack, signed_in

PRIYA = "p.shah@northfieldbank.com"

# Publish requests wait for a reviewer instead of going live at once.
with people_stack(agents_env={"OPS_REGISTRY_AUTO_APPROVE": "false"}) as (api, agents):
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    me = invited(api, priya, f"builder.{secrets.token_hex(3)}@northfieldbank.com", "builder")
    h = bearer(me, "team_ops")

    r = agents.post("/v1/agents", json={"name": f"Desk {secrets.token_hex(2)}", "role": "Answers"}, headers=h)
    agent = data(r) if r.status_code in (200, 201) else {}
    check("the builder creates an agent in the team", bool(agent.get("id")), r.text[:200])
    r = agents.patch(f"/v1/agents/{agent.get('id', 'ag_x')}", json={"role": "Answers branch questions"}, headers=h)
    check("the builder edits it (200)", r.status_code == 200, r.text[:200])
    version = data(r).get("version", agent.get("version", 1)) if r.status_code == 200 else 1
    r = agents.post(f"/v1/agents/{agent.get('id', 'ag_x')}/publish-requests", json={"version": version}, headers=h)
    request = data(r) if r.status_code in (200, 201) else {}
    check("the builder asks to publish, and the request waits", request.get("status") == "pending", r.text[:200])
    r = agents.post(
        f"/v1/publish-requests/{request.get('id', 'pr_x')}/decision", json={"decision": "approved"}, headers=h
    )
    check("the builder cannot decide the review (403)", r.status_code == 403, r.text[:200])
    r = api.post("/v1/settings/members/invite", json={"emails": ["x@northfieldbank.com"], "role": "viewer"}, headers=h)
    check("the builder cannot invite anyone (403)", r.status_code == 403, r.text[:200])
    r = api.put("/v1/policies/requesterMayDecide", json={"value": False}, headers=h)
    check("the builder cannot change a policy (403)", r.status_code == 403, r.text[:200])

finish()
