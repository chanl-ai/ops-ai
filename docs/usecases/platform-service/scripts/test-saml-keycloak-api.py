"""SAML sign-in, step-up, group rules, group removal and the admin's test sign-in, proven against Keycloak (a real
identity provider in Docker, `lib/keycloak_idp.py`) instead of the repo's fake. Covers the paths of uc-162, uc-711 and
uc-713; platform-service still proves the domains against the fake's DNS, which is not what this script tests."""

from __future__ import annotations

import secrets

import httpx
from keycloak_idp import REALM, Keycloak, log_in
from keycloak_idp import browser as new_browser
from usecase_harness import (
    TOOLS_PORT,
    assistant_sign_in,
    bearer,
    check,
    data,
    finish,
    post_saml_form,
    set_provider,
    signed_in,
    signin_stack,
)

WANJIRU = "w.kamau@harborpine.example"
GROUP_MAP = [
    {"group": "platform-readers", "team": "team_platform", "role": "viewer"},
    {"group": "platform-builders", "team": "team_platform", "role": "builder"},
]

kc = Keycloak()


def answer(api: httpx.Client, form: str | None) -> dict[str, str]:
    """Hands Keycloak's answer to platform-service as the browser would; returns the query of where it sends the browser."""
    if form is None:
        return {"error": "keycloak_no_answer"}
    return dict(httpx.URL(post_saml_form(api, form).headers.get("location", "")).params)


def sp_id_of(saved: httpx.Response) -> str:
    """The address id a saved SAML provider's service provider metadata and consumer URL carry (the end of its acsUrl)."""
    return str(data(saved)["saml"]["acsUrl"]).rsplit("/", 1)[1]


with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    wanjiru = signed_in(api, WANJIRU)
    admin = bearer(wanjiru, "team_security")
    provider = {
        "kind": "saml",
        "label": "Keycloak",
        "domains": [zone],
        "saml": {"idpEntityId": kc.entity_id, "ssoUrl": kc.sso_url, "certificate": kc.certificate()},
        "jit": {"team": "team_ops", "role": "chat_user"},
        "groups": {"map": GROUP_MAP},
    }
    r = set_provider(api, idp, "saml-keycloak", provider, admin)
    check(
        "Wanjiru saves a SAML provider that trusts Keycloak's signing certificate (200)",
        r.status_code == 200,
        r.text[:300],
    )
    meta = api.get(f"/v1/auth/saml/metadata/{sp_id_of(r)}")
    check("the provider's own service provider metadata is served (200)", meta.status_code == 200, meta.text[:200])
    kc.register_sp(meta.text)

    def sign_in(
        email: str, browser: httpx.Client | None = None
    ) -> tuple[httpx.Client, dict[str, object], dict[str, str]]:
        """A SAML sign-in at Keycloak: returns the browser (its Keycloak session), the session platform-service gave
        (empty when it refused) and the query of the redirect."""
        browser = browser or new_browser()
        start = api.post("/v1/auth/sso/start", json={"email": email})
        if start.status_code != 200:
            return browser, {}, {"error": f"start_{start.status_code}"}
        form, how = log_in(browser, data(start)["redirectUrl"], email)
        query = answer(api, form) | ({} if form else {"keycloak": how})
        if "code" not in query:
            return browser, {}, query
        done = api.post("/v1/auth/sso/complete", json={"code": query["code"], "flowKey": data(start)["flowKey"]})
        return browser, data(done) if done.status_code == 200 else {}, query

    # 1 A signed assertion from a real provider is accepted, and the NameID email is who signs in.
    ana = f"ana@{zone}"
    kc.make_user(ana, ("platform-readers", "platform-builders", "other"))
    browser, session, query = sign_in(ana)
    principal = session.get("principal", {}) if session else {}
    check(
        "Keycloak's signed assertion signs Ana in by SAML as her email",
        principal.get("authMethod") == "saml" and principal.get("email") == ana,
        query or principal,
    )

    # 2 Keycloak's group-membership attribute reaches the group rules: both groups, the higher role wins.
    roles = dict(principal.get("roles", {}))
    check(
        "Ana's two Keycloak groups give team_platform builder, the higher role, beside team_ops from her first sign-in",
        roles == {"team_ops": "chat_user", "team_platform": "builder"},
        roles,
    )

    # 3 A step-up at the provider asks for credentials again even though Keycloak holds Ana's session.
    start = api.post("/v1/auth/step-up/sso/start", json={"next": "/reviews"}, headers=bearer(session))
    check("the step-up starts at the session's provider (200)", start.status_code == 200, start.text[:200])
    form, how = log_in(browser, data(start)["redirectUrl"], ana) if start.status_code == 200 else (None, "none")
    check("Keycloak asks Ana for her password again for a step-up despite its live session", how == "asked", how)
    query = answer(api, form)
    token = ""
    if "code" in query and start.status_code == 200:
        done = api.post(
            "/v1/auth/step-up/sso/complete",
            json={"code": query["code"], "flowKey": data(start)["flowKey"]},
            headers=bearer(session),
        )
        token = data(done)["token"] if done.status_code == 200 else ""
    check(
        "the fresh login at Keycloak returns a step-up token and sends the console to /reviews",
        bool(token) and query.get("next") == "/reviews",
        query,
    )

    # 4 Leaving a group at the provider ends what it gave, and the assistant connected to that team.
    ana_session = session
    assistants = {
        team: assistant_sign_in(
            api, ana, f"http://127.0.0.1:{TOOLS_PORT}/mcp/{team}", client_name=team, person=ana_session
        )
        for team in ("team_platform", "team_ops")
    }
    uid = next(
        u["id"]
        for u in kc.http.get(
            f"/admin/realms/{REALM}/users", headers=kc.admin, params={"email": ana, "exact": "true"}
        ).json()
    )
    # In no group at all, Keycloak sends no groups attribute; that reads as no groups, not as unknown.
    kc.set_groups(uid, ())
    _, session, query = sign_in(ana)
    roles = dict(session.get("principal", {}).get("roles", {})) if session else {}
    check(
        "after Ana leaves every group at Keycloak, her next sign-in ends team_platform and keeps team_ops",
        roles == {"team_ops": "chat_user"},
        roles or query,
    )

    def renews(team: str) -> int:
        a = assistants[team]
        return api.post(
            "/oauth/token",
            data={"grant_type": "refresh_token", "refresh_token": a["refresh_token"], "client_id": a["client_id"]},
        ).status_code

    renewed = {"team_platform": renews("team_platform"), "team_ops": renews("team_ops")}
    check(
        "her assistant on team_platform is refused a renewal and the one on team_ops renews",
        renewed == {"team_platform": 400, "team_ops": 200},
        renewed,
    )
    ended = data(
        api.get(
            "/v1/audit",
            params={"action": "oauth.grant_ended", "pageSize": 50},
            headers=bearer(wanjiru, "team_platform"),
        )
    )["data"]
    check(
        "the audit names that one assistant connection as ended by group",
        [e.get("detail", {}).get("by") for e in ended] == ["group"],
        ended,
    )

    # 5 The admin's test sign-in reads the email and groups Keycloak really sends.
    off = provider | {"enabled": False, "label": "Keycloak try", "domains": [f"try.{zone}"]}
    r = set_provider(api, idp, "saml-keycloak-try", off, admin)
    kc.register_sp(api.get(f"/v1/auth/saml/metadata/{sp_id_of(r)}").text)
    tester = f"teller@try.{zone}"
    kc.make_user(tester, ("platform-readers",))
    started = data(api.post("/v1/settings/sign-in/providers/saml-keycloak-try/test", headers=admin))
    form, _ = log_in(new_browser(), started["redirectUrl"], tester)
    back = httpx.URL(post_saml_form(api, form).headers.get("location", "")) if form else httpx.URL("")
    result = data(api.get(f"/v1/settings/sign-in/test-results/{started['flowId']}", headers=admin))
    check(
        "the test sign-in shows the email and the one group Keycloak sent",
        back.params.get("test") == started["flowId"]
        and result.get("email") == tester
        and result.get("groups") == ["platform-readers"],
        result,
    )

finish()
