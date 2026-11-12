"""uc-711 leaving a group at the company's identity provider ends only what that group gave, api layer:
docs/usecases/platform-service/saml-group-grants-and-removal.md."""

from __future__ import annotations

import secrets
from typing import Any

from usecase_harness import (
    TOOLS_PORT,
    assistant_sign_in,
    bearer,
    check,
    data,
    finish,
    set_provider,
    signed_in,
    signin_stack,
    sso_round_trip,
)

WANJIRU = "w.kamau@harborpine.example"


def roles_of(round_trip: dict[str, Any]) -> dict[str, str]:
    done = round_trip["completed"]
    return dict(data(done)["principal"]["roles"]) if done is not None and done.status_code == 200 else {}


with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    base = str(idp.base_url).rstrip("/")
    provider = {
        "kind": "saml",
        "label": "Harbor & Pine SAML",
        "domains": [zone],
        "saml": {
            "idpEntityId": f"{base}/saml/northfield",
            "ssoUrl": f"{base}/saml/northfield/sso",
            "certificate": idp.get("/saml/northfield/certificate").text,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
        "groups": {
            "map": [
                {"group": "platform-readers", "team": "team_platform", "role": "viewer"},
                {"group": "platform-builders", "team": "team_platform", "role": "builder"},
            ]
        },
    }
    wanjiru = signed_in(api, WANJIRU)
    r = set_provider(api, idp, "saml-groups", provider, bearer(wanjiru, "team_security"))
    check("Wanjiru maps two groups into team_platform (200)", r.status_code == 200, r.text[:300])
    check(
        "a new provider removes what a group gave by default",
        r.status_code == 200 and data(r)["groups"]["onMissing"] == "remove",
        r.text[:300],
    )

    ana = f"ana@{zone}"
    roles = roles_of(sso_round_trip(api, idp, ana, groups=("platform-readers", "platform-builders")))
    check(
        "Ana, in both groups, lands in team_ops by her first sign-in and team_platform as builder, the higher role",
        roles == {"team_ops": "chat_user", "team_platform": "builder"},
        roles,
    )
    # Ana's assistants: one on team_platform's MCP address (the group gave that team) and one on team_ops's (her first
    # sign-in gave that one).
    ana_session = data(sso_round_trip(api, idp, ana, groups=("platform-readers", "platform-builders"))["completed"])
    assistants = {
        team: assistant_sign_in(
            api, ana, f"http://127.0.0.1:{TOOLS_PORT}/mcp/{team}", client_name=f"uc-711 {team}", person=ana_session
        )
        for team in ("team_platform", "team_ops")
    }
    roles = roles_of(sso_round_trip(api, idp, ana, groups=("platform-readers",), idp_params={"overage": "1"}))
    check(
        "a sign-in carrying Entra's overage claim instead of her groups removes nothing",
        roles.get("team_platform") == "builder",
        roles,
    )
    roles = roles_of(sso_round_trip(api, idp, ana, groups=("other",)))
    check(
        "after she leaves both groups, team_platform ends and her first-sign-in team_ops stays",
        roles == {"team_ops": "chat_user"},
        roles,
    )

    def renews(team: str) -> int:
        a = assistants[team]
        return api.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": a["refresh_token"], "client_id": a["client_id"]},
        ).status_code

    check(
        "5 leaving the group ended Ana's assistant on team_platform, and the one on team_ops still renews",
        renews("team_platform") == 400 and renews("team_ops") == 200,
        {"team_platform": renews("team_platform"), "team_ops": renews("team_ops")},
    )
    ended = data(
        api.get(
            "/v1/audit",
            params={"action": "oauth.grant_ended", "pageSize": 50},
            headers=bearer(wanjiru, "team_platform"),
        )
    )["data"]
    by = [e.get("detail", {}).get("by") for e in ended]
    check(
        "6 the audit names that one assistant connection as ended by group",
        by == ["group"],
        ended,
    )

finish()
