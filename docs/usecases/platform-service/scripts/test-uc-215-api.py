"""uc-215 SAML with signed requests and encrypted assertions, api layer:
docs/usecases/platform-service/saml-signed-requests-and-encrypted-assertions.md."""

from __future__ import annotations

import secrets

import httpx
from usecase_harness import (
    SAML_SP_CERT,
    check,
    data,
    finish,
    security_admin_on_ops,
    set_provider,
    signin_stack,
    sso_round_trip,
)

from ops_signin.fake_idp import self_signed

with signin_stack() as (api, idp, _):
    zone = f"{secrets.token_hex(4)}.harborpine.test"
    base = str(idp.base_url).rstrip("/")
    sam = security_admin_on_ops(api)
    provider = {
        "kind": "saml",
        "label": "Harbor & Pine SAML",
        "domains": [zone],
        "saml": {
            "idpEntityId": f"{base}/saml/strict",
            "ssoUrl": f"{base}/saml/strict/sso",
            "certificate": idp.get("/saml/strict/certificate").text,
            "signRequests": True,
            "requireEncryption": True,
        },
        "jit": {"team": "team_ops", "role": "chat_user"},
    }
    r = set_provider(api, idp, "saml-strict", provider, sam)
    check(
        "Sam sets a SAML provider that signs requests and requires encryption (200)",
        r.status_code == 200 and data(r)["saml"]["signRequests"] is True,
        r.text[:300],
    )
    r = api.get("/v1/auth/saml/metadata")
    body = "".join(line for line in SAML_SP_CERT.splitlines() if "CERTIFICATE" not in line)
    check(
        "the SP metadata carries the certificate for signing and encryption",
        r.status_code == 200 and r.text.count(body) == 2,
        r.text[:200],
    )

    def bank_knows(**sp: object) -> None:
        idp.put("/saml/strict/sp", json=sp).raise_for_status()

    bank_knows(certificate=SAML_SP_CERT, requireSignedRequests=True, encrypt=True, cipher="aes256-cbc")
    first = sso_round_trip(api, idp, f"analyst@{zone}")
    done = first["completed"]
    check(
        "a signed request is accepted and the encrypted assertion signs a new person in",
        done is not None and done.status_code == 200 and data(done)["principal"]["authMethod"] == "saml",
        first["location"],
    )

    _, other = self_signed("uc-other-sp")
    bank_knows(certificate=other, requireSignedRequests=True, encrypt=True)
    start = data(api.post("/v1/auth/sso/start", json={"email": f"x@{zone}"}))
    url = httpx.URL(start["redirectUrl"])
    r = idp.get(url.path, params=dict(url.params) | {"user": f"x@{zone}"})
    check(
        "an identity provider holding another certificate refuses the request (400)", r.status_code == 400, r.text[:200]
    )

    bank_knows(certificate=SAML_SP_CERT, requireSignedRequests=True, encrypt=True, keyTransport="rsa-1_5")
    old = sso_round_trip(api, idp, f"old@{zone}")
    check(
        "an assertion encrypted with the old key transport signs nobody in",
        old["completed"] is None and "error=" in old["location"],
        old["location"],
    )
    bank_knows(certificate=SAML_SP_CERT, requireSignedRequests=True, encrypt=False)
    plain = sso_round_trip(api, idp, f"plain@{zone}")
    check(
        "a plain assertion is refused where encryption is required",
        plain["completed"] is None and "error=" in plain["location"],
        plain["location"],
    )

finish()
