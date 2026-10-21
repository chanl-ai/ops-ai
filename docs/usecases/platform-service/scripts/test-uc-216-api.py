"""uc-216 a person invited as a viewer reads the team's work and changes none of it, api layer:
docs/usecases/platform-service/role-viewer.md."""

from __future__ import annotations

import secrets

from usecase_harness import bearer, check, data, finish, invited, people_stack, signed_in

PRIYA = "p.shah@harborpine.example"

with people_stack() as (api, agents):
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    email = f"viewer.{secrets.token_hex(3)}@harborpine.example"
    me = invited(api, priya, email, "viewer")
    h = bearer(me, "team_ops")
    check(
        "the viewer's token names team_ops as viewer",
        me.get("principal", {}).get("roles") == {"team_ops": "viewer"},
        me.get("principal"),
    )

    listed = agents.get("/v1/agents?page=1&pageSize=5", headers=h)
    rows = data(listed).get("data", []) if listed.status_code == 200 else []
    check("the viewer reads the team's agents (200)", listed.status_code == 200 and bool(rows), listed.text[:200])
    agent = rows[0] if rows else {"id": "ag_missing", "version": 1}
    r = agents.post("/v1/agents", json={"name": "Viewer's agent", "role": "Answers"}, headers=h)
    check("the viewer cannot create an agent (403)", r.status_code == 403, r.text[:200])
    r = agents.patch(f"/v1/agents/{agent['id']}", json={"role": "Changed by a viewer"}, headers=h)
    check("the viewer cannot edit an agent (403)", r.status_code == 403, r.text[:200])
    r = agents.post(f"/v1/agents/{agent['id']}/publish-requests", json={"version": agent.get("version", 1)}, headers=h)
    check("the viewer cannot ask to publish an agent (403)", r.status_code == 403, r.text[:200])
    r = agents.delete(f"/v1/agents/{agent['id']}", headers=h)
    check("the viewer cannot delete an agent (403)", r.status_code == 403, r.text[:200])
    r = api.post("/v1/settings/members/invite", json={"emails": ["x@harborpine.example"], "role": "viewer"}, headers=h)
    check("the viewer cannot invite anyone (403)", r.status_code == 403, r.text[:200])
    r = agents.get("/v1/agents?page=1&pageSize=5", headers=bearer(me, "team_fraud"))
    check(
        "the viewer cannot act in a team they are not in (403 team_forbidden)",
        r.status_code == 403 and r.json()["error"]["code"] == "team_forbidden",
        r.text[:200],
    )

finish()
