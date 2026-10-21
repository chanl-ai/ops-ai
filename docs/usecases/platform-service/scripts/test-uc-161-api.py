"""uc-161 an OIDC sign-in creates a chat-only person once, api layer:
docs/usecases/platform-service/oidc-sign-in-creates-a-chat-user.md."""

from __future__ import annotations

import secrets

from usecase_harness import (
    SIGNIN_SECRET,
    bearer,
    check,
    data,
    finish,
    security_admin_on_ops,
    set_provider,
    signed_in,
    signin_stack,
    sso_round_trip,
)

from ops_access import CHAT_USER

with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    sam = security_admin_on_ops(api)
    provider = {
        "kind": "oidc",
        "label": "Harbor & Pine SSO",
        "domains": [zone],
        "oidc": {
            "issuer": f"{str(idp.base_url).rstrip('/')}/oidc/northfield",
            "clientId": "ops-console",
            "clientSecretRef": SIGNIN_SECRET,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
    }
    r = set_provider(api, idp, "oidc-northfield", provider, sam)
    check("Sam sets the OIDC provider for the domain (200)", r.status_code == 200, r.text[:300])
    r = api.put("/v1/settings/sign-in/providers/password", json={"kind": "password", "label": "Password"}, headers=sam)
    check("Sam keeps passwords on for everyone else (200)", r.status_code == 200, r.text[:200])

    teller = f"new.teller@{zone}"
    r = api.post("/v1/auth/options", json={"email": teller})
    check(
        "the domain signs in through Harbor & Pine SSO",
        r.status_code == 200 and data(r)["sso"] == {"kind": "oidc", "label": "Harbor & Pine SSO"},
        r.text[:200],
    )

    first = sso_round_trip(api, idp, teller)
    done = first["completed"]
    session = data(done) if done is not None and done.status_code == 200 else {}
    principal = session.get("principal", {})
    check(
        "the first sign-in returns an OIDC session as a chat user on team_ops",
        principal.get("authMethod") == "oidc" and principal.get("roles") == {"team_ops": "chat_user"},
        first["location"] or first.get("start"),
    )
    r = api.get("/v1/me/permissions", headers=bearer(session, "team_ops"))
    held = (
        {(p["area"], p["action"]) for t in data(r)["teams"] for p in t["permissions"]}
        if r.status_code == 200
        else set()
    )
    check(
        "the new person holds exactly the Chat user role's rights",
        held == {(a, x) for a, x, _ in CHAT_USER.grants},
        held,
    )
    r = api.get("/v1/settings/members", headers=bearer(session, "team_ops"))
    check("a chat user cannot read the team's members (403)", r.status_code == 403, r.status_code)

    second = sso_round_trip(api, idp, teller)
    again = (
        data(second["completed"])["principal"]
        if second["completed"] is not None and second["completed"].status_code == 200
        else {}
    )
    check("the next sign-in is the same person", again.get("sub") == principal.get("sub") and bool(again), again)
    priya = signed_in(api, "p.shah@harborpine.example")
    rows = data(api.get("/v1/settings/members", headers=bearer(priya, "team_ops")))["data"]
    mine = [m for m in rows if m["email"] == teller]
    check("team_ops lists the teller once, as a chat user", len(mine) == 1 and mine[0]["role"] == "chat_user", mine)

    # Non-vacuous: the provider vouches for an address on a domain it was not given; nobody is made.
    stranger = sso_round_trip(api, idp, f"someone@{zone}", user="ceo@other-bank.test")
    check(
        "an email outside the provider's domains is refused",
        stranger["query"] == {"error": "sign_in_refused"},
        stranger["query"],
    )
    rows = data(api.get("/v1/settings/members", headers=bearer(priya, "team_ops")))["data"]
    check("and no member was made for it", not [m for m in rows if m["email"] == "ceo@other-bank.test"])

finish()
