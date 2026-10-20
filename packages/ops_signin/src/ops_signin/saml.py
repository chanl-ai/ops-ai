"""SAML 2.0 sign-in started by the service provider: the Web Browser SSO profile with the AuthnRequest on the redirect
binding and the Response on the POST binding.

`complete` trusts nothing it has not checked against the configured certificate. The XML signature is verified with
`signxml`, and every value is then read from the element that signature covers, never from the document as posted,
because a second, unsigned assertion placed beside a signed one is the classic way past a SAML check. The response
must hold exactly one assertion, plain or encrypted. The assertion must name the configured issuer, the service
provider as audience, the consumer URL as recipient, answer the request this flow sent, and sit inside its time
window. Text is read with every node joined, so a comment inside the NameID cannot cut it short.

With the service provider's key (c-197), requests are signed on the redirect binding (SAML bindings 3.4.4.1) when the
provider asks, and an `EncryptedAssertion` is decrypted (`xmlenc`). Decryption proves nothing about the sender, so an
encrypted assertion is trusted only when the Response signature, checked before decrypting, covers its ciphertext, or
the decrypted Assertion carries its own signature, checked after. Every decryption failure is one refusal.
"""

from __future__ import annotations

import base64
import secrets
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote_plus, urlencode

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from lxml import etree
from lxml.etree import _Element as Element  # pyright: ignore[reportPrivateUsage]
from signxml.algorithms import DigestAlgorithm, SignatureMethod
from signxml.exceptions import InvalidInput, InvalidSignature
from signxml.verifier import SignatureConfiguration, VerifyResult, XMLVerifier

from . import xmlenc
from .identity import SignInRefused, VerifiedIdentity

PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
NS = {"samlp": PROTOCOL, "saml": ASSERTION}
POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
SUCCESS = "urn:oasis:names:tc:SAML:2.0:status:Success"
BEARER = "urn:oasis:names:tc:SAML:2.0:cm:bearer"
EMAIL_FORMAT = "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
METADATA = "urn:oasis:names:tc:SAML:2.0:metadata"
DSIG = "http://www.w3.org/2000/09/xmldsig#"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
DECRYPT_REFUSED = "the encrypted assertion could not be read"
# A posted response larger than this is refused before it is parsed.
MAX_RESPONSE_BYTES = 256 * 1024
_SIGNATURE = SignatureConfiguration(
    require_x509=False,
    expect_references=1,
    signature_methods=frozenset(
        {
            SignatureMethod.RSA_SHA256,
            SignatureMethod.RSA_SHA384,
            SignatureMethod.RSA_SHA512,
            SignatureMethod.ECDSA_SHA256,
            SignatureMethod.ECDSA_SHA384,
            SignatureMethod.ECDSA_SHA512,
        }
    ),
    digest_algorithms=frozenset({DigestAlgorithm.SHA256, DigestAlgorithm.SHA384, DigestAlgorithm.SHA512}),
)


def _parser() -> etree.XMLParser:
    return etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


def _instant(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _text(el: Element | None) -> str:
    return "".join(el.itertext()).strip() if el is not None else ""


@dataclass(frozen=True)
class SamlConfig:
    idp_entity_id: str
    idp_sso_url: str
    # The identity provider's signing certificate, PEM.
    idp_certificate: str
    sp_entity_id: str
    acs_url: str
    # The attribute that carries the email; None reads it from the NameID.
    email_attribute: str | None = None
    name_attribute: str | None = None
    # The attribute whose values are the person's groups; None reads none.
    groups_attribute: str | None = None
    # The service provider's private key, PEM: signs requests and decrypts assertions (c-197). None: neither.
    sp_key: str | None = None
    sign_requests: bool = False
    # A plain assertion is refused: the provider must encrypt to the service provider's certificate.
    require_encryption: bool = False


@dataclass(frozen=True)
class SamlStart:
    url: str
    request_id: str


@dataclass(frozen=True)
class SamlServiceProvider:
    config: SamlConfig
    skew_s: int = 120

    def begin(self, *, relay_state: str, force: bool = False, now: datetime | None = None) -> SamlStart:
        c = self.config
        request_id = f"_{secrets.token_hex(20)}"
        req = etree.Element(
            f"{{{PROTOCOL}}}AuthnRequest",
            nsmap={"samlp": PROTOCOL, "saml": ASSERTION},
            ID=request_id,
            Version="2.0",
            IssueInstant=_instant(now or datetime.now(UTC)),
            Destination=c.idp_sso_url,
            AssertionConsumerServiceURL=c.acs_url,
            ProtocolBinding=POST_BINDING,
        )
        if force:
            # The provider must ask for credentials again; its own session is not enough for a step-up.
            req.set("ForceAuthn", "true")
        etree.SubElement(req, f"{{{ASSERTION}}}Issuer").text = c.sp_entity_id
        etree.SubElement(req, f"{{{PROTOCOL}}}NameIDPolicy", Format=EMAIL_FORMAT, AllowCreate="true")
        deflate = zlib.compressobj(wbits=-15)
        raw = deflate.compress(etree.tostring(req)) + deflate.flush()
        query = urlencode({"SAMLRequest": base64.b64encode(raw).decode(), "RelayState": relay_state})
        if c.sign_requests:
            if c.sp_key is None:
                raise SignInRefused("signed requests need the service provider key")
            # The signature covers the query exactly as sent, SigAlg last (SAML bindings 3.4.4.1).
            query = f"{query}&SigAlg={quote_plus(RSA_SHA256)}"
            signature = _private_key(c.sp_key).sign(query.encode(), padding.PKCS1v15(), hashes.SHA256())
            query = f"{query}&Signature={quote_plus(base64.b64encode(signature).decode())}"
        return SamlStart(f"{c.idp_sso_url}{'&' if '?' in c.idp_sso_url else '?'}{query}", request_id)

    def complete(
        self, *, saml_response: str, request_id: str, now: datetime | None = None, fresh_since: int | None = None
    ) -> VerifiedIdentity:
        """`fresh_since` (Unix seconds) is set for a forced sign-in: the assertion's AuthnInstant must not be older."""
        c = self.config
        now = now or datetime.now(UTC)
        try:
            raw = base64.b64decode(saml_response, validate=True)
        except ValueError as e:
            raise SignInRefused("response is not base64") from e
        if len(raw) > MAX_RESPONSE_BYTES:
            raise SignInRefused("response too large")
        try:
            posted = etree.fromstring(raw, parser=_parser())
        except etree.XMLSyntaxError as e:
            raise SignInRefused("response is not XML") from e
        if posted.tag != f"{{{PROTOCOL}}}Response":
            raise SignInRefused("not a SAML response")
        encrypted = posted.findall(".//saml:EncryptedAssertion", NS)
        plain = posted.findall(".//saml:Assertion", NS)
        if encrypted:
            if c.sp_key is None:
                raise SignInRefused("encrypted assertions need the service provider key")
            if len(encrypted) != 1 or plain:
                raise SignInRefused("the response must hold exactly one assertion")
        elif c.require_encryption:
            raise SignInRefused("the provider must encrypt its assertions")
        elif len(plain) != 1:
            raise SignInRefused("the response must hold exactly one assertion")
        status = posted.find("samlp:Status/samlp:StatusCode", NS)
        if status is None or status.get("Value") != SUCCESS:
            raise SignInRefused("the provider did not report success")
        if posted.get("InResponseTo") not in (None, request_id):
            raise SignInRefused("response answers another request")
        if posted.get("Destination") not in (None, c.acs_url):
            raise SignInRefused("response is for another destination")
        if encrypted:
            assertion = self._decrypted(raw, posted, encrypted[0])
            return self._read(assertion, request_id=request_id, now=now, fresh_since=fresh_since)
        try:
            result: VerifyResult | list[VerifyResult] = XMLVerifier().verify(  # pyright: ignore[reportUnknownMemberType]
                raw, x509_cert=c.idp_certificate, id_attribute="ID", expect_config=_SIGNATURE, parser=_parser()
            )
        except (InvalidSignature, InvalidInput, ValueError) as e:
            raise SignInRefused(f"signature refused: {e}") from e
        if isinstance(result, list):
            raise SignInRefused("more than one signature")
        signed = result.signed_xml
        if signed is None:
            raise SignInRefused("nothing was signed")
        if signed.tag == f"{{{ASSERTION}}}Assertion":
            assertion = signed
        elif signed.tag == f"{{{PROTOCOL}}}Response":
            found = signed.findall("saml:Assertion", NS)
            if len(found) != 1:
                raise SignInRefused("the signed response must hold exactly one assertion")
            assertion = found[0]
        else:
            raise SignInRefused("the signature covers neither the response nor the assertion")
        return self._read(assertion, request_id=request_id, now=now, fresh_since=fresh_since)

    def _decrypted(self, raw: bytes, posted: Element, encrypted: Element) -> Element:
        """The assertion inside `encrypted`, taken from whichever element a checked signature covers."""
        key = self.config.sp_key
        assert key is not None
        try:
            xmlenc.check_algorithms(encrypted)
        except xmlenc.UnsupportedAlgorithm as e:
            raise SignInRefused(f"unsupported encryption: {e}") from e
        if posted.find(f"{{{DSIG}}}Signature") is not None:
            # The Response is signed: its signature covers the ciphertext, so decrypt what it covers.
            signed = _verified(raw, self.config.idp_certificate)
            inner = signed.findall("saml:EncryptedAssertion", NS) if signed.tag == f"{{{PROTOCOL}}}Response" else []
            if len(inner) != 1:
                raise SignInRefused("the signature covers neither the response nor the assertion")
            return _assertion_of(_decrypt(inner[0], key))
        plaintext = _decrypt(encrypted, key)
        # Parsed before the signature check, so content that decrypts to anything but an assertion gets the one
        # decryption refusal, never a signature error that tells it apart.
        _assertion_of(plaintext)
        signed = _verified(plaintext, self.config.idp_certificate)
        if signed.tag != f"{{{ASSERTION}}}Assertion":
            raise SignInRefused("the signature covers neither the response nor the assertion")
        return signed

    def _read(self, a: Element, *, request_id: str, now: datetime, fresh_since: int | None) -> VerifiedIdentity:
        c = self.config
        if _text(a.find("saml:Issuer", NS)) != c.idp_entity_id:
            raise SignInRefused("assertion from another issuer")
        cond = a.find("saml:Conditions", NS)
        if cond is None:
            raise SignInRefused("assertion has no conditions")
        self._window(cond.get("NotBefore"), cond.get("NotOnOrAfter"), now)
        audiences = {_text(x) for x in cond.findall("saml:AudienceRestriction/saml:Audience", NS)}
        if c.sp_entity_id not in audiences:
            raise SignInRefused("assertion is for another audience")
        confirmed = False
        for sc in a.findall("saml:Subject/saml:SubjectConfirmation", NS):
            data = sc.find("saml:SubjectConfirmationData", NS)
            if sc.get("Method") != BEARER or data is None:
                continue
            if data.get("Recipient") != c.acs_url or data.get("InResponseTo") != request_id:
                continue
            until = _parse_instant(data.get("NotOnOrAfter"))
            if until is None or until.timestamp() <= now.timestamp() - self.skew_s:
                continue
            confirmed = True
        if not confirmed:
            raise SignInRefused("no bearer confirmation for this request and recipient")
        subject = _text(a.find("saml:Subject/saml:NameID", NS))
        if not subject:
            raise SignInRefused("assertion names nobody")
        attrs = {
            str(x.get("Name")): _text(x.find("saml:AttributeValue", NS))
            for x in a.findall("saml:AttributeStatement/saml:Attribute", NS)
        }
        email = (attrs.get(c.email_attribute, "") if c.email_attribute else subject).strip().lower()
        if "@" not in email:
            raise SignInRefused("no email")
        authn = a.find("saml:AuthnStatement", NS)
        instant = _parse_instant(authn.get("AuthnInstant") if authn is not None else None)
        auth_time = int(instant.timestamp()) if instant else None
        if fresh_since is not None and (auth_time is None or auth_time < fresh_since - self.skew_s):
            raise SignInRefused("the provider did not ask for credentials again")
        name = attrs.get(c.name_attribute, "") if c.name_attribute else ""
        groups = tuple(
            _text(v)
            for x in a.findall("saml:AttributeStatement/saml:Attribute", NS)
            if c.groups_attribute and x.get("Name") == c.groups_attribute
            for v in x.findall("saml:AttributeValue", NS)
        )
        return VerifiedIdentity(subject=subject, email=email, name=name or email, auth_time=auth_time, groups=groups)

    def _window(self, not_before: str | None, not_on_or_after: str | None, now: datetime) -> None:
        start, end = _parse_instant(not_before), _parse_instant(not_on_or_after)
        t = now.timestamp()
        if start is not None and start.timestamp() > t + self.skew_s:
            raise SignInRefused("assertion not yet valid")
        if end is None or end.timestamp() <= t - self.skew_s:
            raise SignInRefused("assertion expired")


def _private_key(pem: str) -> rsa.RSAPrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise SignInRefused("the service provider key is not an RSA key")
    return key


def _decrypt(encrypted: Element, key: str) -> bytes:
    try:
        return xmlenc.decrypt(encrypted, key)
    except xmlenc.DecryptionRefused as e:
        raise SignInRefused(DECRYPT_REFUSED) from e


def _assertion_of(plaintext: bytes) -> Element:
    try:
        assertion = xmlenc.parse(plaintext)
    except xmlenc.DecryptionRefused as e:
        raise SignInRefused(DECRYPT_REFUSED) from e
    if assertion.tag != f"{{{ASSERTION}}}Assertion":
        raise SignInRefused(DECRYPT_REFUSED)
    return assertion


def _verified(document: bytes, certificate: str) -> Element:
    """The element the document's one signature covers, checked against the provider's certificate."""
    try:
        result: VerifyResult | list[VerifyResult] = XMLVerifier().verify(  # pyright: ignore[reportUnknownMemberType]
            document, x509_cert=certificate, id_attribute="ID", expect_config=_SIGNATURE, parser=_parser()
        )
    except (InvalidSignature, InvalidInput, ValueError) as e:
        raise SignInRefused(f"signature refused: {e}") from e
    if isinstance(result, list):
        raise SignInRefused("more than one signature")
    if result.signed_xml is None:
        raise SignInRefused("nothing was signed")
    return result.signed_xml


def sp_metadata(*, entity_id: str, acs_url: str, certificate: str | None, sign_requests: bool) -> bytes:
    """The service provider's metadata for a bank's identity provider: who it is, where answers go, and the
    certificate that checks its requests and that assertions are encrypted to (SAML metadata 2.4.4)."""
    root = etree.Element(f"{{{METADATA}}}EntityDescriptor", nsmap={"md": METADATA, "ds": DSIG}, entityID=entity_id)
    sp = etree.SubElement(
        root,
        f"{{{METADATA}}}SPSSODescriptor",
        AuthnRequestsSigned="true" if sign_requests else "false",
        WantAssertionsSigned="true",
        protocolSupportEnumeration=PROTOCOL,
    )
    if certificate:
        body = "".join(line for line in certificate.strip().splitlines() if "CERTIFICATE" not in line)
        for use in ("signing", "encryption"):
            kd = etree.SubElement(sp, f"{{{METADATA}}}KeyDescriptor", use=use)
            data = etree.SubElement(etree.SubElement(kd, f"{{{DSIG}}}KeyInfo"), f"{{{DSIG}}}X509Data")
            etree.SubElement(data, f"{{{DSIG}}}X509Certificate").text = body
    etree.SubElement(sp, f"{{{METADATA}}}NameIDFormat").text = EMAIL_FORMAT
    etree.SubElement(sp, f"{{{METADATA}}}AssertionConsumerService", Binding=POST_BINDING, Location=acs_url, index="0")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")
