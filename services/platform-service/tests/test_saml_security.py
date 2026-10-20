"""SAML with the service provider's key (c-197), through the routes, by failure mode: a provider that asks for signed
requests or encryption is saved where no key is set (F1); an identity provider checking signatures accepts a request
signed with another key (F2); an encrypted assertion signs nobody in end to end, or a plain one passes where encryption
is required (F6); the metadata does not carry the certificate a bank's identity provider needs."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from ops_platform.signin_settings import SignInSettings
from ops_service_kit.errors import ValidationFailed
from ops_signin.dns import TxtResolver
from ops_signin.fake_idp import self_signed

from .conftest import IDP, SP_CERT, SignInRig


async def _saml(rig: SignInRig, domain: str, **flags: bool) -> dict[str, Any]:
    cert = (await rig.idp.get("/saml/bank/certificate")).text
    return {
        "kind": "saml",
        "label": "Bank SAML",
        "domains": [domain],
        "saml": {"idpEntityId": f"{IDP}/saml/bank", "ssoUrl": f"{IDP}/saml/bank/sso", "certificate": cert, **flags},
        "jit": {"team": rig.ops_team, "role": "chat_user"},
    }


async def _bank_knows(rig: SignInRig, **sp: Any) -> None:
    assert (await rig.idp.put("/saml/bank/sp", json=sp)).status_code == 200


async def test_signed_requests_and_encrypted_assertions_sign_in_end_to_end(signin: SignInRig) -> None:
    domain = f"enc.{signin.zone}"
    r = await signin.configure("sip_enc", await _saml(signin, domain, signRequests=True, requireEncryption=True))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["saml"]["signRequests"] is True
    await _bank_knows(signin, certificate=SP_CERT, requireSignedRequests=True, encrypt=True, cipher="aes256-cbc")
    done = await signin.sign_in_sso(f"ana@{domain}")
    assert done.completed is not None and done.completed.status_code == 200, done.location


async def test_an_identity_provider_refuses_a_request_signed_with_another_key(signin: SignInRig) -> None:
    domain = f"key.{signin.zone}"
    assert (await signin.configure("sip_key", await _saml(signin, domain, signRequests=True))).status_code == 200
    _, other = self_signed("someone-else")
    await _bank_knows(signin, certificate=other, requireSignedRequests=True)
    start = (await signin.public.post("/v1/auth/sso/start", json={"email": f"x@{domain}"})).json()["data"]
    url = httpx.URL(start["redirectUrl"])
    refused = await signin.idp.get(url.path, params=dict(url.params) | {"user": f"x@{domain}"})
    assert refused.status_code == 400 and "not signed by the service provider" in refused.text


async def test_a_plain_assertion_is_refused_where_encryption_is_required(signin: SignInRig) -> None:
    domain = f"plain.{signin.zone}"
    r = await signin.configure("sip_plain", await _saml(signin, domain, requireEncryption=True))
    assert r.status_code == 200, r.text
    await _bank_knows(signin, certificate=SP_CERT, encrypt=False)
    done = await signin.sign_in_sso(f"bo@{domain}")
    assert done.completed is None and "error=" in done.location, done.location


def test_a_provider_asking_for_the_key_is_refused_where_none_is_set() -> None:
    settings = SignInSettings(store=None, members=None, secrets={}, dns=TxtResolver(), sp_key_set=False)  # type: ignore[arg-type]
    body = {"saml": {"idpEntityId": "x", "ssoUrl": "https://idp/sso", "certificate": SP_CERT, "signRequests": True}}
    with pytest.raises(ValidationFailed) as refused:
        settings._config("saml", body)  # pyright: ignore[reportPrivateUsage]
    assert refused.value.code == "sp_key_missing"


async def test_the_metadata_carries_the_certificate_and_the_consumer(signin: SignInRig) -> None:
    r = await signin.public.get("/v1/auth/saml/metadata")
    body = "".join(line for line in SP_CERT.splitlines() if "CERTIFICATE" not in line)
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/samlmetadata+xml")
    assert r.text.count(body) == 2 and "/v1/auth/saml/acs" in r.text
