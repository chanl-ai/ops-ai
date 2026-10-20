"""uc-220 a person invited as a Security team admin sets sign-in and policies, and the right moves with the security
team, api layer: docs/usecases/platform-service/role-security-admin.md."""

from __future__ import annotations

import secrets

from usecase_harness import bearer, check, finish, invited, people_stack, signed_in

SAM, PRIYA, WANJIRU = "s.adeyemi@northfieldbank.com", "p.shah@northfieldbank.com", "w.kamau@northfieldbank.com"
PASSWORD_PROVIDER = {"kind": "password", "label": "Password"}

with people_stack() as (api, _):
    sam = bearer(signed_in(api, SAM), "team_security")
    sec = bearer(invited(api, sam, f"sec.{secrets.token_hex(3)}@northfieldbank.com", "admin"), "team_security")

    r = api.put("/v1/settings/sign-in/providers/password", json=PASSWORD_PROVIDER, headers=sec)
    check("the Security team admin sets a sign-in provider (200)", r.status_code == 200, r.text[:200])
    r = api.put("/v1/policies/requesterMayDecide", json={"value": False}, headers=sec)
    check("the Security team admin changes a policy (200)", r.status_code == 200, r.text[:200])

    priya = bearer(signed_in(api, PRIYA), "team_ops")
    r = api.put("/v1/settings/sign-in/providers/password", json=PASSWORD_PROVIDER, headers=priya)
    check("an admin of another team cannot set sign-in providers (403)", r.status_code == 403, r.text[:200])
    r = api.put("/v1/policies/requesterMayDecide", json={"value": True}, headers=priya)
    check("an admin of another team cannot change a workspace policy (403)", r.status_code == 403, r.text[:200])

    wanjiru = bearer(signed_in(api, WANJIRU))
    r = api.put("/v1/settings/workspace-teams", json={"securityTeam": "team_ops", "defaultTeam": None}, headers=wanjiru)
    check("Wanjiru makes team_ops the security team", r.status_code == 200, r.text[:200])
    r = api.put("/v1/settings/sign-in/providers/password", json=PASSWORD_PROVIDER, headers=sec)
    check("the old Security team's admin loses the right (403)", r.status_code == 403, r.text[:200])
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    r = api.put("/v1/settings/sign-in/providers/password", json=PASSWORD_PROVIDER, headers=priya)
    check("team_ops's admin now holds it (200)", r.status_code == 200, r.text[:200])

finish()
