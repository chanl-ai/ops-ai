"""A local identity provider for tests and the dev stack, never for a deployment: it signs in whoever the request
names. It serves any number of named providers, each with its own signing key, as OpenID Connect at `/oidc/<name>`
(discovery, authorize, token, keys) and as SAML at `/saml/<name>` (SSO and certificate), so a test can sign in at one
and present the answer to a service configured for another.

The person "logs in" by the `user` query parameter on the authorize or SSO URL (the email; `login_hint` when absent),
which stands in for the provider's own login form. Each provider remembers when a person last logged in: a request
without `prompt=login` (OIDC) or `ForceAuthn` (SAML) reuses that time, as a real provider's session cookie would, and
`stale=1` makes it ignore a forced login too, so a test can show the service refusing an old authentication.
"""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, unquote_plus, urlencode

import jwt
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from jwt.algorithms import RSAAlgorithm
from lxml import etree
from lxml.etree import _Element as Element  # pyright: ignore[reportPrivateUsage]
from signxml.algorithms import CanonicalizationMethod
from signxml.signer import XMLSigner

from .dns import FakeDns
from .encrypt import encrypt_assertion

PROTOCOL = "urn:oasis:names:tc:SAML:2.0:protocol"
RSA_SHA256 = "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256"
ASSERTION = "urn:oasis:names:tc:SAML:2.0:assertion"
_NS = {"samlp": PROTOCOL, "saml": ASSERTION}


@dataclass
class Idp:
    name: str
    key: rsa.RSAPrivateKey
    cert_pem: str
    kid: str
    logins: dict[str, int] = field(default_factory=dict[str, int])
    codes: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    # What this provider knows of the service provider (c-197): its certificate, whether requests must be signed,
    # and how to encrypt assertions to it.
    sp: dict[str, Any] = field(default_factory=dict[str, Any])

    def login_time(self, email: str, *, forced: bool, stale: bool) -> int:
        now = int(time.time())
        if email not in self.logins:
            # A first login an hour ago, so a step-up that reuses it is visibly old.
            self.logins[email] = now - 3600
        if forced and not stale:
            self.logins[email] = now
        return self.logins[email]

    def key_pem(self) -> bytes:
        return self.key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )


def self_signed(name: str) -> tuple[str, str]:
    """A fresh RSA key and its self-signed certificate, both PEM: a service provider's key pair for tests."""
    pair = _new_idp(name)
    return pair.key_pem().decode(), pair.cert_pem


def _new_idp(name: str) -> Idp:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"fake-idp-{name}")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return Idp(name, key, cert.public_bytes(serialization.Encoding.PEM).decode(), kid=f"{name}-{secrets.token_hex(4)}")


def subject_of(email: str) -> str:
    """The provider's stable id for a person: the same for one email at one provider."""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:24]


def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(base_url: str, dns_records: FakeDns | None = None) -> FastAPI:
    """`base_url` is this server's public origin, which every issuer and endpoint URL is built on. `dns_records` is
    the fake DNS server whose TXT records `PUT /dns/txt/{domain}` sets, so a test publishes a domain's proof here."""
    base = base_url.rstrip("/")
    idps: dict[str, Idp] = {}
    app = FastAPI(title="Fake identity provider")
    fake_dns = dns_records or FakeDns()

    @app.put("/dns/txt/{domain}")
    async def publish_txt(domain: str, request: Request) -> dict[str, list[str]]:  # pyright: ignore[reportUnusedFunction]
        body = await request.json()
        values = [str(v) for v in body.get("values", [])]
        fake_dns.records[domain.lower()] = values
        return {"values": values}

    def idp(name: str) -> Idp:
        if name not in idps:
            idps[name] = _new_idp(name)
        return idps[name]

    @app.get("/health")
    async def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    # ── OpenID Connect ──

    @app.get("/oidc/{name}/.well-known/openid-configuration")
    async def discovery(name: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        issuer = f"{base}/oidc/{name}"
        idp(name)
        return {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/authorize",
            "token_endpoint": f"{issuer}/token",
            "jwks_uri": f"{issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
        }

    @app.get("/oidc/{name}/jwks")
    async def jwks(name: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        i = idp(name)
        jwk: dict[str, Any] = RSAAlgorithm.to_jwk(i.key.public_key(), as_dict=True)
        return {"keys": [jwk | {"kid": i.kid, "use": "sig", "alg": "RS256"}]}

    @app.get("/oidc/{name}/authorize")
    async def authorize(name: str, request: Request) -> RedirectResponse:  # pyright: ignore[reportUnusedFunction]
        q = request.query_params
        email = (q.get("user") or q.get("login_hint") or "").strip().lower()
        if not email or q.get("response_type") != "code" or q.get("code_challenge_method") != "S256":
            raise HTTPException(400, "user, response_type=code and S256 are required")
        i = idp(name)
        forced = q.get("prompt") == "login" or q.get("max_age") == "0"
        code = secrets.token_urlsafe(24)
        i.codes[code] = {
            "client_id": q.get("client_id"),
            "redirect_uri": q.get("redirect_uri"),
            "challenge": q.get("code_challenge"),
            "nonce": q.get("nonce"),
            "email": email,
            "auth_time": i.login_time(email, forced=forced, stale=q.get("stale") == "1"),
            "groups": [g for g in q.get("groups", "").split(",") if g],
        }
        target = str(q.get("redirect_uri"))
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}{urlencode({'code': code, 'state': q.get('state', '')})}", 302)

    @app.post("/oidc/{name}/token")
    async def token(name: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
        grant_type, code, redirect_uri = form.get("grant_type"), form.get("code", ""), form.get("redirect_uri")
        code_verifier, client_id = form.get("code_verifier", ""), form.get("client_id")
        i = idp(name)
        grant = i.codes.pop(code, None)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip("=")
        if (
            grant is None
            or grant_type != "authorization_code"
            or grant["redirect_uri"] != redirect_uri
            or grant["client_id"] != client_id
            or grant["challenge"] != challenge
        ):
            raise HTTPException(400, "invalid_grant")
        now = int(time.time())
        claims = {
            "iss": f"{base}/oidc/{name}",
            "aud": client_id,
            "sub": subject_of(grant["email"]),
            "email": grant["email"],
            "email_verified": True,
            "name": grant["email"].split("@")[0].replace(".", " ").title(),
            "nonce": grant["nonce"],
            "iat": now,
            "exp": now + 300,
            "auth_time": grant["auth_time"],
            "groups": grant["groups"],
        }
        id_token = jwt.encode(claims, i.key_pem(), algorithm="RS256", headers={"kid": i.kid})
        return {"access_token": secrets.token_urlsafe(16), "token_type": "Bearer", "id_token": id_token}

    # ── SAML ──

    @app.get("/saml/{name}/certificate", response_class=PlainTextResponse)
    async def certificate(name: str) -> str:  # pyright: ignore[reportUnusedFunction]
        return idp(name).cert_pem

    @app.put("/saml/{name}/sp")
    async def service_provider(name: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """`{certificate, requireSignedRequests, encrypt, cipher, keyTransport, signAssertion, signResponse}`."""
        idp(name).sp = dict(await request.json())
        return idp(name).sp

    @app.get("/saml/{name}/sso", response_class=HTMLResponse)
    async def sso(name: str, request: Request) -> str:  # pyright: ignore[reportUnusedFunction]
        q = request.query_params
        email = (q.get("user") or "").strip().lower()
        known = idp(name).sp
        if known.get("requireSignedRequests") and not _signed_by(request.url.query, str(known.get("certificate", ""))):
            raise HTTPException(400, "the request is not signed by the service provider")
        try:
            xml = zlib.decompress(base64.b64decode(q.get("SAMLRequest", "")), wbits=-15)
            req = etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True))
        except (ValueError, zlib.error, etree.XMLSyntaxError) as e:
            raise HTTPException(400, "SAMLRequest unreadable") from e
        if not email:
            raise HTTPException(400, "user is required")
        i = idp(name)
        acs = str(req.get("AssertionConsumerServiceURL"))
        sp = "".join(req.find("saml:Issuer", _NS).itertext())  # type: ignore[union-attr]
        forced = req.get("ForceAuthn") == "true"
        auth_time = i.login_time(email, forced=forced, stale=q.get("stale") == "1")
        response = saml_response(
            i,
            issuer=f"{base}/saml/{name}",
            audience=sp,
            acs=acs,
            in_response_to=str(req.get("ID")),
            email=email,
            auth_time=auth_time,
            groups=[g for g in q.get("groups", "").split(",") if g],
            encrypt_to=str(known["certificate"]) if known.get("encrypt") else None,
            cipher=str(known.get("cipher", "aes256-gcm")),
            key_transport=str(known.get("keyTransport", "rsa-oaep-mgf1p")),
            sign_assertion=bool(known.get("signAssertion", True)),
            sign_response=bool(known.get("signResponse", False)),
        )
        fields = {"SAMLResponse": response, "RelayState": q.get("RelayState", "")}
        inputs = "".join(
            f'<input type="hidden" name="{k}" value="{html.escape(v, quote=True)}">' for k, v in fields.items()
        )
        return (
            f'<html><body onload="document.forms[0].submit()"><form method="post" action="{html.escape(acs)}">'
            f"{inputs}</form></body></html>"
        )

    return app


def saml_response(
    i: Idp,
    *,
    issuer: str,
    audience: str,
    acs: str,
    in_response_to: str,
    email: str,
    auth_time: int,
    groups: list[str] | None = None,
    encrypt_to: str | None = None,
    cipher: str = "aes256-gcm",
    key_transport: str = "rsa-oaep-mgf1p",
    sign_assertion: bool = True,
    sign_response: bool = False,
) -> str:
    """A Response holding one assertion signed with the provider's key, base64 as the POST binding sends it. With
    `encrypt_to` (a certificate) the assertion is encrypted to it; `sign_response` signs the Response around it."""
    now = datetime.now(UTC)
    later = now + timedelta(minutes=5)
    response = etree.Element(
        f"{{{PROTOCOL}}}Response",
        nsmap={"samlp": PROTOCOL, "saml": ASSERTION},
        ID=f"_{secrets.token_hex(16)}",
        Version="2.0",
        IssueInstant=_iso(now),
        Destination=acs,
        InResponseTo=in_response_to,
    )
    etree.SubElement(response, f"{{{ASSERTION}}}Issuer").text = issuer
    status = etree.SubElement(response, f"{{{PROTOCOL}}}Status")
    etree.SubElement(status, f"{{{PROTOCOL}}}StatusCode", Value="urn:oasis:names:tc:SAML:2.0:status:Success")
    a = etree.Element(f"{{{ASSERTION}}}Assertion", nsmap={"saml": ASSERTION}, ID=f"_{secrets.token_hex(16)}")
    a.set("Version", "2.0")
    a.set("IssueInstant", _iso(now))
    etree.SubElement(a, f"{{{ASSERTION}}}Issuer").text = issuer
    subject = etree.SubElement(a, f"{{{ASSERTION}}}Subject")
    name_id = etree.SubElement(
        subject, f"{{{ASSERTION}}}NameID", Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
    )
    name_id.text = email
    sc = etree.SubElement(
        subject, f"{{{ASSERTION}}}SubjectConfirmation", Method="urn:oasis:names:tc:SAML:2.0:cm:bearer"
    )
    etree.SubElement(
        sc,
        f"{{{ASSERTION}}}SubjectConfirmationData",
        InResponseTo=in_response_to,
        Recipient=acs,
        NotOnOrAfter=_iso(later),
    )
    cond = etree.SubElement(
        a, f"{{{ASSERTION}}}Conditions", NotBefore=_iso(now - timedelta(minutes=1)), NotOnOrAfter=_iso(later)
    )
    restriction = etree.SubElement(cond, f"{{{ASSERTION}}}AudienceRestriction")
    etree.SubElement(restriction, f"{{{ASSERTION}}}Audience").text = audience
    etree.SubElement(a, f"{{{ASSERTION}}}AuthnStatement", AuthnInstant=_iso(datetime.fromtimestamp(auth_time, UTC)))
    attrs = etree.SubElement(a, f"{{{ASSERTION}}}AttributeStatement")
    for key, value in (("email", email), ("displayName", email.split("@", maxsplit=1)[0].replace(".", " ").title())):
        attr = etree.SubElement(attrs, f"{{{ASSERTION}}}Attribute", Name=key)
        etree.SubElement(attr, f"{{{ASSERTION}}}AttributeValue").text = value
    if groups:
        attr = etree.SubElement(attrs, f"{{{ASSERTION}}}Attribute", Name="groups")
        for g in groups:
            etree.SubElement(attr, f"{{{ASSERTION}}}AttributeValue").text = g
    signer = XMLSigner(c14n_algorithm=CanonicalizationMethod.EXCLUSIVE_XML_CANONICALIZATION_1_0)
    signed: Element = (
        signer.sign(  # pyright: ignore[reportUnknownMemberType]
            a, key=i.key_pem(), cert=i.cert_pem, reference_uri=a.get("ID"), id_attribute="ID"
        )
        if sign_assertion
        else a
    )
    response.append(
        encrypt_assertion(signed, encrypt_to, cipher=cipher, key_transport=key_transport) if encrypt_to else signed
    )
    if sign_response:
        response = signer.sign(  # pyright: ignore[reportUnknownMemberType]
            response, key=i.key_pem(), cert=i.cert_pem, reference_uri=response.get("ID"), id_attribute="ID"
        )
    return base64.b64encode(etree.tostring(response)).decode()


def _signed_by(raw_query: str, certificate: str) -> bool:
    """Whether the redirect-binding query carries a valid RSA-SHA256 signature by `certificate` over
    `SAMLRequest=…&RelayState=…&SigAlg=…`, taken exactly as sent (SAML bindings 3.4.4.1)."""
    parts = dict(p.split("=", 1) for p in raw_query.split("&") if "=" in p)
    if not certificate or "Signature" not in parts or unquote_plus(parts.get("SigAlg", "")) != RSA_SHA256:
        return False
    signed = "&".join(f"{k}={parts[k]}" for k in ("SAMLRequest", "RelayState", "SigAlg") if k in parts)
    public = x509.load_pem_x509_certificate(certificate.encode()).public_key()
    if not isinstance(public, rsa.RSAPublicKey):
        return False
    try:
        public.verify(
            base64.b64decode(unquote_plus(parts["Signature"])), signed.encode(), padding.PKCS1v15(), hashes.SHA256()
        )
    except (InvalidSignature, ValueError):
        return False
    return True
