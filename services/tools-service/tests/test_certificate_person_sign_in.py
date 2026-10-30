"""A person's own sign-in on a connection whose app proves itself with its certificate (c-583), by failure mode: the
code exchange or the disconnect's revocation sends the client secret, or no proof, instead of a signed assertion."""

from __future__ import annotations

import httpx
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from . import test_personal_sign_in as personal
from .test_assertion import pair, parts
from .test_personal_sign_in import client, system  # noqa: F401  # pyright: ignore[reportUnusedImport]

ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"


async def test_a_persons_sign_in_and_disconnect_send_the_signed_assertion(
    client: httpx.AsyncClient,  # noqa: F811
    tenant: str,
    system: personal.System,  # noqa: F811
) -> None:
    admin = personal.person(tenant, "Priya Shah", {personal.TEAM: "admin"})
    security = personal.person(tenant, "Sam Adeyemi", {"team_security": "admin"})
    await client.post("/v1/egress/hosts", json={"value": "login.bank.test"}, headers=security)
    made = await client.post(
        "/v1/connections", json={"name": "CRM", "authKind": "oauth2_auth_code", "signIn": "person"}, headers=admin
    )
    conn = str(made.json()["data"]["id"])
    key_pem, cert_pem, cert = pair()
    settings = {
        **personal.SETTINGS,
        "revokeUrl": "https://login.bank.test/revoke",
        "clientAuth": "private_key_jwt",
        "signingCertificate": cert_pem,
    }
    body = {"revision": 1, "settings": settings, "secretValues": {"signingKey": key_pem, "clientSecret": "unused"}}
    put = await client.put(f"/v1/connections/{conn}/environments/test", json=body, headers=admin)
    assert put.status_code == 200, put.text
    await personal.sign_in(client, tenant, conn, personal.JAMES_P, "james")
    gone = await client.delete(
        f"/v1/me/connections/{conn}", params={"environment": "test"}, headers=personal.person(tenant, *personal.JAMES_P)
    )
    assert gone.status_code == 204, gone.text
    for form in (system.asked[0], system.revoked[0]):
        assert form.get("client_assertion_type") == ASSERTION and "client_secret" not in form, form
        _, claims, signed, signature = parts(form["client_assertion"])
        cert.public_key().verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        assert (claims["iss"], claims["aud"]) == ("ops-console", personal.SETTINGS["tokenUrl"])
