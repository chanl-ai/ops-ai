"""uc-163 a sign-in by another method or provider than the workspace's is refused, api layer:
docs/usecases/platform-service/wrong-sign-in-provider-refused.md."""

from __future__ import annotations

import html
import re
import secrets

import httpx
from usecase_harness import (
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

with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.northfield.test"
    base = str(idp.base_url).rstrip("/")
    priya = signed_in(api, "p.shah@northfieldbank.com")
    saml = {
        "kind": "saml",
        "label": "Northfield SAML",
        "domains": [zone],
        "saml": {
            "idpEntityId": f"{base}/saml/northfield",
            "ssoUrl": f"{base}/saml/northfield/sso",
            "certificate": idp.get("/saml/northfield/certificate").text,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
    }
    r = set_provider(api, idp, "saml-northfield", saml, bearer(priya, "team_ops"))
    check("a team admin outside the Security team cannot set providers (403)", r.status_code == 403, r.status_code)
    sam = security_admin_on_ops(api)
    r = set_provider(api, idp, "saml-northfield", saml, sam)
    check("Sam makes the workspace SAML-only (200)", r.status_code == 200, r.text[:300])

    r = api.post("/v1/auth/sign-in", json={"email": "j.richardson@northfieldbank.com", "password": "northfield-demo"})
    check("a password sign-in in the SAML-only workspace is refused (401)", r.status_code == 401, r.status_code)

    # The SAML request answered by another provider's key.
    start = api.post("/v1/auth/sso/start", json={"email": f"x@{zone}"})
    url = httpx.URL(data(start)["redirectUrl"])
    page = idp.get("/saml/elsewhere/sso", params=dict(url.params) | {"user": f"x@{zone}"})
    form = {k: html.unescape(v) for k, v in re.findall(r'name="(\w+)" value="([^"]*)"', page.text)}
    r = api.post(
        "/v1/auth/saml/acs",
        content=str(httpx.QueryParams(form)),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    query = dict(httpx.URL(r.headers.get("location", "")).params)
    check(
        "an answer signed by another provider is refused",
        r.status_code == 303 and query == {"error": "sign_in_refused"},
        query,
    )

    # A valid answer from the configured provider, replayed: its flow was spent.
    good = sso_round_trip(api, idp, f"y@{zone}")
    check(
        "the configured provider signs a person in",
        good["completed"] is not None and good["completed"].status_code == 200,
        good["location"],
    )
    r = api.post(
        "/v1/auth/sso/complete",
        json={"code": good["query"].get("code", "x" * 20), "flowKey": good["flowKey"] or "x" * 20},
    )
    check("the same code a second time is refused (401)", r.status_code == 401, r.status_code)
    r = api.post("/v1/auth/sso/start", json={"email": "p.shah@northfieldbank.com"})
    check(
        "an email domain with no provider cannot start SSO (400)",
        r.status_code == 400 and r.json()["error"]["code"] == "sso_not_enabled",
        r.text[:200],
    )

finish()
