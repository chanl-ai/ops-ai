"""uc-162 SAML sign-in and step-up at the same provider, api layer:
docs/usecases/platform-service/saml-sign-in-and-step-up.md."""

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
    signin_stack,
    sso_round_trip,
)

with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.northfield.test"
    base = str(idp.base_url).rstrip("/")
    sam = security_admin_on_ops(api)
    provider = {
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
    r = set_provider(api, idp, "saml-northfield", provider, sam)
    check("Sam sets the SAML provider for the domain (200)", r.status_code == 200, r.text[:300])

    analyst = f"analyst@{zone}"
    first = sso_round_trip(api, idp, analyst)
    done = first["completed"]
    session = data(done) if done is not None and done.status_code == 200 else {}
    check(
        "a SAML sign-in returns a SAML session",
        session.get("principal", {}).get("authMethod") == "saml",
        first["location"],
    )

    r = api.post("/v1/auth/step-up", json={"password": "northfield-demo"}, headers=bearer(session))
    check(
        "a password step-up is refused for a SAML session (401 wrong_method)",
        r.status_code == 401 and r.json()["error"]["code"] == "wrong_method",
        r.text[:200],
    )

    def step_up(*, stale: bool) -> tuple[dict[str, str], httpx.Response | None]:
        start = api.post("/v1/auth/step-up/sso/start", json={"next": "/reviews"}, headers=bearer(session))
        check(
            "the step-up starts at the session's own provider",
            start.status_code == 200 and "/saml/northfield/sso" in data(start)["redirectUrl"],
            start.text[:200],
        )
        url = httpx.URL(data(start)["redirectUrl"])
        params = dict(url.params) | {"user": analyst} | ({"stale": "1"} if stale else {})
        page = idp.get(url.path, params=params)
        form = {k: html.unescape(v) for k, v in re.findall(r'name="(\w+)" value="([^"]*)"', page.text)}
        back = api.post(
            "/v1/auth/saml/acs",
            content=str(httpx.QueryParams(form)),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        query = dict(httpx.URL(back.headers.get("location", "")).params)
        if "code" not in query:
            return query, None
        return query, api.post(
            "/v1/auth/step-up/sso/complete",
            json={"code": query["code"], "flowKey": data(start)["flowKey"]},
            headers=bearer(session),
        )

    query, _ = step_up(stale=True)
    check(
        "a provider that reuses its earlier login does not pass a step-up",
        query.get("error") == "sign_in_refused" and query.get("stepUp") == "1",
        query,
    )
    query, done = step_up(stale=False)
    token = data(done)["token"] if done is not None and done.status_code == 200 else ""
    check(
        "a fresh login at the provider returns a step-up token", bool(token) and query.get("next") == "/reviews", query
    )

finish()
