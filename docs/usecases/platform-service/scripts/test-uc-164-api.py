"""uc-164 workspace admins create, rename, archive and restore teams, api layer:
docs/usecases/platform-service/workspace-admins-manage-teams.md."""

from __future__ import annotations

from usecase_harness import bearer, check, data, every_page, finish, platform, signed_in

WANJIRU, SAM, PRIYA, RAVI = (
    "w.kamau@harborpine.example",
    "s.adeyemi@harborpine.example",
    "p.shah@harborpine.example",
    "r.menon@harborpine.example",
)

with platform() as (api, _):
    admin = bearer(signed_in(api, WANJIRU))
    priya = bearer(signed_in(api, PRIYA), "team_ops")
    r = api.post("/v1/settings/teams", json={"name": "Treasury", "admin": RAVI}, headers=priya)
    check("Priya, admin of team_ops only, cannot create a team (403)", r.status_code == 403, r.status_code)
    sam = bearer(signed_in(api, SAM), "team_security")
    r = api.post("/v1/settings/teams", json={"name": "Treasury", "admin": RAVI}, headers=sam)
    check("Sam, Security admin but no admin in every team, cannot either (403)", r.status_code == 403, r.text[:300])

    r = api.post("/v1/settings/teams", json={"name": "Lending", "admin": RAVI}, headers=admin)
    team = data(r) if r.status_code == 201 else {}
    check(
        "Wanjiru, a workspace admin, creates Lending with Ravi as its first admin (201)",
        team.get("adminCount") == 1,
        r.text[:200],
    )
    team_id = team.get("id", "team_missing")
    ravi = signed_in(api, RAVI)
    check(
        "Ravi's next token carries Lending as its admin",
        ravi.get("principal", {}).get("roles", {}).get(team_id) == "admin",
    )
    r = api.post("/v1/settings/teams", json={"name": "LENDING", "admin": RAVI}, headers=admin)
    check(
        "a second Lending in any case is refused (409 team_name_taken)",
        r.status_code == 409 and r.json()["error"]["code"] == "team_name_taken",
        r.text[:200],
    )

    r = api.patch(f"/v1/settings/teams/{team_id}", json={"name": "Retail Lending"}, headers=admin)
    check("she renames it", r.status_code == 200 and data(r)["name"] == "Retail Lending", r.text[:200])
    his = bearer(signed_in(api, RAVI))
    mine = every_page(api, "/v1/teams", headers=his, search="Retail Lending")
    check(
        "Ravi's team switcher finds it by its new name",
        any(t["id"] == team_id and t["name"] == "Retail Lending" for t in mine),
        mine,
    )
    one = data(api.get("/v1/teams", params={"pageSize": 1}, headers=his))
    check(
        "his teams come a page at a time with their total",
        len(one["data"]) == 1 and one["pagination"]["total"] >= 2 and one["pagination"]["hasNext"],
        {"rows": [t["name"] for t in one["data"]], "pagination": one["pagination"]},
    )

    r = api.post(f"/v1/settings/teams/{team_id}/archive", headers=admin)
    check("she archives it", r.status_code == 200 and data(r)["status"] == "archived", r.text[:200])
    after = signed_in(api, RAVI)
    check("Ravi's next token no longer carries it", team_id not in after.get("principal", {}).get("teamIds", []))
    r = api.post(
        "/v1/settings/members/invite",
        json={"emails": ["new@harborpine.example"], "role": "viewer"},
        headers=bearer(ravi, team_id),
    )
    check("an invitation into the archived team is refused", r.status_code in (403, 409), r.status_code)
    r = api.post("/v1/settings/teams/team_security/archive", headers=admin)
    check(
        "the Security team cannot be archived (409 security_team)",
        r.status_code == 409 and r.json()["error"]["code"] == "security_team",
        r.text[:200],
    )

    r = api.post(f"/v1/settings/teams/{team_id}/restore", headers=admin)
    back = signed_in(api, RAVI)
    check(
        "restored, it is back in Ravi's next token",
        r.status_code == 200 and team_id in back.get("principal", {}).get("teamIds", []),
    )
    listed = data(api.get("/v1/settings/teams", params={"search": "lending"}, headers=admin))
    check(
        "the workspace list shows it with its counts from the API",
        [(t["name"], t["memberCount"], t["adminCount"]) for t in listed["data"]] == [("Retail Lending", 1, 1)],
        listed,
    )

finish()
