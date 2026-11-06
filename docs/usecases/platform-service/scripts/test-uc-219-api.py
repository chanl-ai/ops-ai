"""uc-219 a person invited as an admin runs their team's people, and only their team's, api layer:
docs/usecases/platform-service/role-admin.md."""

from __future__ import annotations

import secrets

import httpx
from usecase_harness import INVITED_PASSWORD, bearer, check, data, finish, invited, people_stack, signed_in

PRIYA = "p.shah@harborpine.example"


def member(api: httpx.Client, h: dict[str, str], email: str) -> str:
    return next((m["id"] for m in data(api.get("/v1/settings/members", headers=h))["data"] if m["email"] == email), "")


with people_stack() as (api, _):
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    admin_email = f"admin.{secrets.token_hex(3)}@harborpine.example"
    admin = bearer(invited(api, priya, admin_email, "admin"), "team_ops")

    person_email = f"person.{secrets.token_hex(3)}@harborpine.example"
    person = invited(api, admin, person_email, "viewer")
    check(
        "the new admin's invitee joins team_ops as viewer",
        person.get("principal", {}).get("roles") == {"team_ops": "viewer"},
    )
    pid = member(api, admin, person_email)
    r = api.post("/v1/settings/members/role", json={"ids": [pid], "role": "builder"}, headers=admin)
    check("the admin makes them a builder", r.status_code == 200 and data(r)["updated"] == [pid], r.text[:200])
    r = api.post("/v1/auth/sign-in", json={"email": person_email, "password": INVITED_PASSWORD})
    check(
        "the role change is in the person's next token",
        r.status_code == 200 and data(r)["principal"]["roles"] == {"team_ops": "builder"},
        r.text[:200],
    )
    r = api.post("/v1/settings/members/delete", json={"ids": [pid]}, headers=admin)
    check("the admin removes them", r.status_code == 200 and data(r)["updated"] == [pid], r.text[:200])
    r = api.post("/v1/auth/sign-in", json={"email": person_email, "password": INVITED_PASSWORD})
    # Removal is from the team, not the workspace: the account stays, the next token carries no team.
    check(
        "the removed person's next token no longer carries team_ops",
        r.status_code != 200 or "team_ops" not in data(r)["principal"]["teamIds"],
        r.text[:200],
    )

    other = {**admin, "X-Team-Id": "team_fraud"}
    r = api.post(
        "/v1/settings/members/invite", json={"emails": ["y@harborpine.example"], "role": "viewer"}, headers=other
    )
    check("the admin cannot invite into a team they are not in (403)", r.status_code == 403, r.text[:200])

    # Priya owns the workspace, so a team admin never removes her: she transfers it first (E42).
    r = api.post("/v1/settings/members/delete", json={"ids": [member(api, admin, PRIYA)]}, headers=admin)
    check(
        "the admin cannot remove Priya, the workspace's owner (409)",
        r.status_code == 409 and r.json()["error"]["code"] == "owner_must_transfer",
        r.text[:200],
    )
    # A team Priya makes with the new admin as its only admin: there they cannot step down.
    desk = api.post(
        "/v1/settings/teams", json={"name": f"Desk {secrets.token_hex(2)}", "admin": admin_email}, headers=priya
    )
    check("Priya makes a team with the new admin as its admin (201)", desk.status_code == 201, desk.text[:200])
    desk_id = str((data(desk) or {}).get("id", "team_x"))
    admin = bearer(signed_in(api, admin_email, INVITED_PASSWORD), desk_id)
    me = member(api, admin, admin_email)
    r = api.post("/v1/settings/members/role", json={"ids": [me], "role": "viewer"}, headers=admin)
    check(
        "the last admin cannot demote themselves",
        r.status_code == 200 and data(r) == {"updated": [], "skipped": [{"id": me, "reason": "last_admin"}]},
        r.text[:200],
    )

finish()
