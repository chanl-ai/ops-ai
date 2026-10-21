"""uc-212 a workspace sets its security and default teams, and SSO groups map people to teams, api layer:
docs/usecases/platform-service/workspace-security-default-teams-and-groups.md."""

from __future__ import annotations

import base64
import json
import secrets

from usecase_harness import (
    SIGNIN_SECRET,
    bearer,
    check,
    data,
    finish,
    set_provider,
    signed_in,
    signin_stack,
    sso_round_trip,
)

WANJIRU, PRIYA, SAM = "w.kamau@harborpine.example", "p.shah@harborpine.example", "s.adeyemi@harborpine.example"


def access(session: dict[str, object], team: str) -> list[str]:
    token = str(session.get("token", "a.e30.b"))
    claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
    return list(claims.get("access", {}).get(team, []))


with signin_stack() as (api, idp, _):
    admin = bearer(signed_in(api, WANJIRU))
    r = api.put(
        "/v1/settings/workspace-teams",
        json={"securityTeam": "team_ops"},
        headers=bearer(signed_in(api, PRIYA), "team_ops"),
    )
    check("Priya, a team admin, cannot set the workspace's teams (403)", r.status_code == 403, r.status_code)
    check("Sam holds Security admin in team_security", "security_admin" in access(signed_in(api, SAM), "team_security"))

    r = api.post("/v1/settings/teams", json={"name": "Lobby", "admin": "r.menon@harborpine.example"}, headers=admin)
    lobby = data(r)["id"] if r.status_code == 201 else "team_missing"
    check("Wanjiru creates Lobby (201)", r.status_code == 201, r.text[:200])
    r = api.put("/v1/settings/workspace-teams", json={"securityTeam": "team_ops", "defaultTeam": lobby}, headers=admin)
    check("Wanjiru makes team_ops the security team and Lobby the default team", r.status_code == 200, r.text[:200])
    check(
        "Priya, admin of team_ops, now holds Security admin there",
        "security_admin" in access(signed_in(api, PRIYA), "team_ops"),
    )
    check(
        "Sam no longer holds it in team_security", "security_admin" not in access(signed_in(api, SAM), "team_security")
    )
    me = data(api.get("/v1/me", headers=admin))
    check(
        "/v1/me names team_ops as the security team", me.get("securityTeamId") == "team_ops", me.get("securityTeamId")
    )

    zone = f"{secrets.token_hex(4)}.harborpine.test"
    base = str(idp.base_url).rstrip("/")
    provider = {
        "kind": "oidc",
        "label": "Harbor & Pine SSO",
        "domains": [zone],
        "oidc": {"issuer": f"{base}/oidc/northfield", "clientId": "ops-console", "clientSecretRef": SIGNIN_SECRET},
        "jit": {"role": "chat_user"},
        "groups": {"map": [{"group": "fraud-analysts", "team": "team_fraud", "role": "viewer"}]},
    }
    r = set_provider(api, idp, "oidc-northfield", provider, bearer(signed_in(api, WANJIRU), "team_security"))
    check("Wanjiru sets an OIDC provider with a role and no team, and a group map", r.status_code == 200, r.text[:300])
    first = sso_round_trip(api, idp, f"analyst@{zone}", groups=("fraud-analysts", "other"))
    roles = (
        data(first["completed"])["principal"]["roles"]
        if first["completed"] is not None and first["completed"].status_code == 200
        else {}
    )
    check(
        "a new person lands in Lobby as a chat user and in team_fraud through the group",
        roles == {lobby: "chat_user", "team_fraud": "viewer"},
        roles or first["location"],
    )
    plain = sso_round_trip(api, idp, f"teller@{zone}")
    roles = (
        data(plain["completed"])["principal"]["roles"]
        if plain["completed"] is not None and plain["completed"].status_code == 200
        else {}
    )
    check("a person without the group lands in Lobby only", roles == {lobby: "chat_user"}, roles)

finish()
