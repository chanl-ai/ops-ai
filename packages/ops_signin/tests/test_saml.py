"""SAML sign-in, by failure mode (c-188 F4): a response signed by another provider, an unsigned assertion wrapped
around a signed one, an edited signed assertion, another audience, recipient or request, an expired assertion, a
failed status, and a step-up on an old login."""

from __future__ import annotations

import base64
import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from lxml import etree
from lxml.etree import _Element as Element  # pyright: ignore[reportPrivateUsage]

from ops_signin import SamlConfig, SamlServiceProvider, SignInRefused
from ops_signin.fake_idp import Idp, saml_response, self_signed
from ops_signin.fake_idp.app import _new_idp, _signed_by  # pyright: ignore[reportPrivateUsage]
from ops_signin.saml import DECRYPT_REFUSED, sp_metadata

BANK, OTHER = _new_idp("bank"), _new_idp("other")
ISSUER = "https://idp.test/saml/bank"
SP = "https://ops.test/saml"
ACS = "https://ops.test/v1/auth/saml/acs"
CONFIG = SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS)
NS = {"samlp": "urn:oasis:names:tc:SAML:2.0:protocol", "saml": "urn:oasis:names:tc:SAML:2.0:assertion"}


def response(
    request_id: str,
    *,
    by: Idp = BANK,
    audience: str = SP,
    acs: str = ACS,
    email: str = "ana@bank.test",
    auth_time: int | None = None,
) -> str:  # type: ignore[no-untyped-def]
    return saml_response(
        by,
        issuer=ISSUER,
        audience=audience,
        acs=acs,
        in_response_to=request_id,
        email=email,
        auth_time=auth_time if auth_time is not None else int(datetime.now(UTC).timestamp()),
    )


def edit(encoded: str, change: Callable[[Element], None]) -> str:
    root = etree.fromstring(base64.b64decode(encoded))
    change(root)
    return base64.b64encode(etree.tostring(root)).decode()


def test_a_response_signed_by_the_configured_provider_signs_in() -> None:
    sp = SamlServiceProvider(CONFIG)
    start = sp.begin(relay_state="r")
    who = sp.complete(saml_response=response(start.request_id), request_id=start.request_id)
    assert (who.subject, who.email) == ("ana@bank.test", "ana@bank.test")


def _one(root: Element, path: str) -> Element:
    found = root.find(path, NS)
    assert found is not None
    return found


def _wrap(root: Element) -> None:
    # An unsigned assertion for someone else placed before the signed one.
    forged = etree.fromstring(etree.tostring(_one(root, "saml:Assertion")))
    for sig in forged.findall("ds:Signature", {"ds": "http://www.w3.org/2000/09/xmldsig#"}):
        forged.remove(sig)
    forged.set("ID", "_forged")
    _one(forged, "saml:Subject/saml:NameID").text = "mallory@bank.test"
    root.insert(2, forged)


def _rename(root: Element) -> None:
    _one(root, "saml:Assertion/saml:Subject/saml:NameID").text = "mallory@bank.test"


def _drop_outer(root: Element) -> None:
    for name in ("Destination", "InResponseTo"):
        root.attrib.pop(name, None)


def _fail_status(root: Element) -> None:
    _one(root, "samlp:Status/samlp:StatusCode").set("Value", "urn:oasis:names:tc:SAML:2.0:status:Requester")


REFUSED: dict[str, Callable[[str], str]] = {
    "signed by another provider": lambda rid: response(rid, by=OTHER),
    "wrapped around a forged assertion": lambda rid: edit(response(rid), _wrap),
    "signed assertion edited": lambda rid: edit(response(rid), _rename),
    "another audience": lambda rid: response(rid, audience="https://other.test/saml"),
    "another recipient": lambda rid: response(rid, acs="https://other.test/acs"),
    "another request": lambda rid: response("_an_earlier_request"),
    # The outer Response's own Destination and InResponseTo are optional and unsigned; with them gone, only the
    # signed confirmation inside the assertion can refuse.
    "another recipient, outer destination dropped": lambda rid: edit(
        response(rid, acs="https://other.test/acs"), _drop_outer
    ),
    "another request, outer reference dropped": lambda rid: edit(response("_an_earlier_request"), _drop_outer),
    "failed status": lambda rid: edit(response(rid), _fail_status),
    "not base64": lambda rid: "%%%",
}


@pytest.mark.parametrize("case", list(REFUSED))
def test_a_response_that_proves_nothing_is_refused(case: str) -> None:
    sp = SamlServiceProvider(CONFIG)
    start = sp.begin(relay_state="r")
    with pytest.raises(SignInRefused):
        sp.complete(saml_response=REFUSED[case](start.request_id), request_id=start.request_id)


def test_an_assertion_past_its_window_is_refused() -> None:
    sp = SamlServiceProvider(CONFIG)
    start = sp.begin(relay_state="r")
    later = datetime.now(UTC) + timedelta(minutes=30)
    with pytest.raises(SignInRefused, match="expired"):
        sp.complete(saml_response=response(start.request_id), request_id=start.request_id, now=later)


def test_a_forced_sign_in_refuses_an_old_login() -> None:
    sp = SamlServiceProvider(CONFIG)
    start = sp.begin(relay_state="r", force=True)
    now = int(datetime.now(UTC).timestamp())
    old = response(start.request_id, auth_time=now - 3600)
    with pytest.raises(SignInRefused, match="again"):
        sp.complete(saml_response=old, request_id=start.request_id, fresh_since=now)
    who = sp.complete(saml_response=response(start.request_id), request_id=start.request_id, fresh_since=now)
    assert who.email == "ana@bank.test"


def test_the_request_names_the_consumer_and_asks_again_when_forced() -> None:
    start = SamlServiceProvider(CONFIG).begin(relay_state="flow-1", force=True)
    q = parse_qs(urlparse(start.url).query)
    req = etree.fromstring(zlib.decompress(base64.b64decode(q["SAMLRequest"][0]), wbits=-15))
    assert (req.get("ID"), req.get("AssertionConsumerServiceURL"), req.get("ForceAuthn")) == (
        start.request_id,
        ACS,
        "true",
    )
    assert q["RelayState"] == ["flow-1"]


def test_groups_are_read_from_the_named_attribute_of_the_signed_assertion() -> None:
    sp = SamlServiceProvider(SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS, groups_attribute="groups"))
    start = sp.begin(relay_state="r")
    signed = saml_response(
        BANK, issuer=ISSUER, audience=SP, acs=ACS, in_response_to=start.request_id, email="ana@bank.test",
        auth_time=int(datetime.now(UTC).timestamp()), groups=["tellers", "branch-12"],
    )  # fmt: skip
    assert sp.complete(saml_response=signed, request_id=start.request_id).groups == ("tellers", "branch-12")
    # A provider that names no groups attribute reads none, whatever the assertion carries.
    plain = SamlServiceProvider(CONFIG)
    start = plain.begin(relay_state="r")
    carried = saml_response(
        BANK, issuer=ISSUER, audience=SP, acs=ACS, in_response_to=start.request_id, email="ana@bank.test",
        auth_time=int(datetime.now(UTC).timestamp()), groups=["tellers"],
    )  # fmt: skip
    assert plain.complete(saml_response=carried, request_id=start.request_id).groups == ()


# ── Signed requests and encrypted assertions (c-197) ──
# F1 a request that should be signed goes out unsigned; F2 a request signed by another key passes; F3 old key transport,
# an unknown cipher or the wrong key is read; F4 a decrypted assertion no signature covers signs in; F5 a tampered
# ciphertext is refused with a different reason; F6 a plain assertion passes where encryption is required.

SP_KEY, SP_CERT = self_signed("sp")
OTHER_KEY, OTHER_CERT = self_signed("sp-other")
SECURE = SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS, sp_key=SP_KEY, sign_requests=True)


def sealed(request_id: str, **kw: object) -> str:
    return saml_response(
        BANK,
        issuer=ISSUER,
        audience=SP,
        acs=ACS,
        in_response_to=request_id,
        email="ana@bank.test",
        auth_time=int(datetime.now(UTC).timestamp()),
        encrypt_to=SP_CERT,
        **kw,  # type: ignore[arg-type]
    )


def test_a_signed_request_verifies_with_the_sp_certificate_only() -> None:
    url = urlparse(SamlServiceProvider(SECURE).begin(relay_state="r/1").url)
    assert "SigAlg=" in url.query and "Signature=" in url.query
    assert _signed_by(url.query, SP_CERT)
    assert not _signed_by(url.query, OTHER_CERT)
    assert not _signed_by(url.query.replace("RelayState=r%2F1", "RelayState=r%2F2"), SP_CERT)
    with pytest.raises(SignInRefused):
        SamlServiceProvider(SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS, sign_requests=True)).begin(
            relay_state="r"
        )


@pytest.mark.parametrize("cipher", ["aes128-gcm", "aes256-gcm", "aes128-cbc", "aes256-cbc"])
def test_an_encrypted_signed_assertion_signs_in(cipher: str) -> None:
    sp = SamlServiceProvider(SECURE)
    start = sp.begin(relay_state="r")
    who = sp.complete(saml_response=sealed(start.request_id, cipher=cipher), request_id=start.request_id)
    assert who.email == "ana@bank.test"


def test_a_signed_response_covers_an_encrypted_unsigned_assertion() -> None:
    sp = SamlServiceProvider(SECURE)
    start = sp.begin(relay_state="r")
    raw = sealed(start.request_id, sign_assertion=False, sign_response=True)
    assert sp.complete(saml_response=raw, request_id=start.request_id).email == "ana@bank.test"


def test_an_encrypted_assertion_no_signature_covers_is_refused() -> None:
    sp = SamlServiceProvider(SECURE)
    start = sp.begin(relay_state="r")
    with pytest.raises(SignInRefused, match="signature"):
        sp.complete(saml_response=sealed(start.request_id, sign_assertion=False), request_id=start.request_id)


def test_old_key_transport_and_the_wrong_key_are_refused() -> None:
    sp = SamlServiceProvider(SECURE)
    start = sp.begin(relay_state="r")
    with pytest.raises(SignInRefused, match="unsupported encryption: key transport"):
        sp.complete(saml_response=sealed(start.request_id, key_transport="rsa-1_5"), request_id=start.request_id)
    wrong = SamlServiceProvider(SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS, sp_key=OTHER_KEY))
    with pytest.raises(SignInRefused, match=DECRYPT_REFUSED):
        wrong.complete(saml_response=sealed(start.request_id), request_id=start.request_id)


@pytest.mark.parametrize("cipher", ["aes256-gcm", "aes256-cbc"])
def test_a_tampered_ciphertext_gets_the_one_decryption_refusal(cipher: str) -> None:
    sp = SamlServiceProvider(SECURE)
    start = sp.begin(relay_state="r")

    def flip(root: Element) -> None:
        value = root.findall(".//{http://www.w3.org/2001/04/xmlenc#}CipherValue")[-1]
        blob = bytearray(base64.b64decode(value.text or ""))
        blob[40] ^= 0x01
        value.text = base64.b64encode(bytes(blob)).decode()

    with pytest.raises(SignInRefused) as refused:
        sp.complete(saml_response=edit(sealed(start.request_id, cipher=cipher), flip), request_id=start.request_id)
    assert refused.value.reason == DECRYPT_REFUSED


def test_a_plain_assertion_is_refused_where_encryption_is_required() -> None:
    strict = SamlServiceProvider(
        SamlConfig(ISSUER, f"{ISSUER}/sso", BANK.cert_pem, SP, ACS, sp_key=SP_KEY, require_encryption=True)
    )
    start = strict.begin(relay_state="r")
    with pytest.raises(SignInRefused, match="encrypt"):
        strict.complete(saml_response=response(start.request_id), request_id=start.request_id)


def test_the_metadata_names_the_consumer_and_the_certificate() -> None:
    xml = sp_metadata(entity_id=SP, acs_url=ACS, certificate=SP_CERT, sign_requests=True).decode()
    body = "".join(line for line in SP_CERT.splitlines() if "CERTIFICATE" not in line)
    assert f'Location="{ACS}"' in xml and 'AuthnRequestsSigned="true"' in xml and xml.count(body) == 2
