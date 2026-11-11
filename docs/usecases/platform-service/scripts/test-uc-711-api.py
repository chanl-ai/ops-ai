"""uc-711 leaving a group at the company's identity provider ends only what that group gave, api layer:
docs/usecases/platform-service/saml-group-grants-and-removal.md."""

from __future__ import annotations

import secrets
from typing import Any

from usecase_harness import bearer, check, data, finish, set_provider, signed_in, signin_stack, sso_round_trip

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
    r = set_provider(api, idp, "saml-groups", provider, bearer(signed_in(api, WANJIRU), "team_security"))
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

finish()
