"""uc-713 an admin tests a company provider before anyone signs in through it, api layer:
docs/usecases/platform-service/saml-test-sign-in.md."""

from __future__ import annotations

import secrets

import httpx
from usecase_harness import bearer, check, data, finish, post_saml_form, set_provider, signed_in, signin_stack

WANJIRU = "w.kamau@harborpine.example"

with signin_stack() as (api, idp, _):
    admin = bearer(signed_in(api, WANJIRU), "team_security")
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    base = str(idp.base_url).rstrip("/")
    provider = {
        "kind": "saml",
        "label": "Harbor & Pine SAML",
        "enabled": False,
        "domains": [zone],
        "saml": {
            "idpEntityId": f"{base}/saml/northfield",
            "ssoUrl": f"{base}/saml/northfield/sso",
            "certificate": idp.get("/saml/northfield/certificate").text,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
        "groups": {"map": [{"group": "platform-readers", "team": "team_platform", "role": "viewer"}]},
    }
    r = set_provider(api, idp, "saml-try", provider, admin)
    check("Wanjiru saves the provider turned off (200)", r.status_code == 200, r.text[:200])

    r = api.post("/v1/settings/sign-in/providers/saml-try/test", headers=admin)
    check("Wanjiru starts a test sign-in (200)", r.status_code == 200, r.text[:200])
    started = data(r) if r.status_code == 200 else {"redirectUrl": "http://x/", "flowId": ""}
    person = f"new.teller@{zone}"
    url = httpx.URL(started["redirectUrl"])
    page = idp.get(url.path, params=dict(url.params) | {"user": person, "groups": "platform-readers"})
    back = httpx.URL(post_saml_form(api, page.text).headers.get("location", ""))
    check(
        "the provider's answer lands on the sign-in settings with the test's id",
        back.path == "/settings/security/sign-in" and back.params.get("test") == started["flowId"],
        str(back),
    )
    result = data(api.get(f"/v1/settings/sign-in/test-results/{started['flowId']}", headers=admin))
    check(
        "the result shows the email and groups the provider sent",
        result.get("state") == "ok" and result.get("email") == person and result.get("groups") == ["platform-readers"],
        result,
    )
    r = api.post("/v1/auth/sso/start", json={"email": person})
    check(
        "a real sign-in is refused while the provider is off, and the test made nobody",
        r.status_code == 400 and r.json()["error"]["code"] == "sso_not_enabled",
        r.text[:200],
    )

finish()
