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
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
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
# What Entra ID sends in place of the groups list for a person in more than 150 groups.
GROUPS_OVERAGE = "http://schemas.microsoft.com/claims/groups.link"


@dataclass
class Idp:
    name: str
    key: rsa.RSAPrivateKey
    cert_pem: str
    kid: str
    logins: dict[str, int] = field(default_factory=dict[str, int])
    codes: dict[str, dict[str, Any]] = field(default_factory=dict[str, dict[str, Any]])
    # What this provider knows of the service provider: its certificate, whether requests must be signed,
    # and how to encrypt assertions to it.
    sp: dict[str, Any] = field(default_factory=dict[str, Any])
    # Certificates its metadata still lists after a rollover, and an entity id its metadata names instead of its own.
    previous: list[str] = field(default_factory=list[str])
    metadata_entity: str | None = None

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


def _certificate(name: str, key: rsa.RSAPrivateKey, *, starts: timedelta, ends: timedelta) -> str:
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"fake-idp-{name}")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now + starts)
        .not_valid_after(now + ends)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def _new_idp(name: str, *, valid_days: int = 365) -> Idp:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = _certificate(name, key, starts=timedelta(days=-1), ends=timedelta(days=valid_days))
    return Idp(name, key, cert, kid=f"{name}-{secrets.token_hex(4)}")


def expired_idp(name: str) -> Idp:
    """A provider whose only certificate ended yesterday: it still signs, with a key nobody should trust now."""
    i = _new_idp(name)
    i.cert_pem = _certificate(name, i.key, starts=timedelta(days=-400), ends=timedelta(days=-1))
    return i


def metadata_xml(base: str, i: Idp) -> bytes:
    """The provider's SAML metadata: entity id, redirect sign-in URL and every signing certificate it lists."""
    md, ds = "urn:oasis:names:tc:SAML:2.0:metadata", "http://www.w3.org/2000/09/xmldsig#"
    root = etree.Element(
        f"{{{md}}}EntityDescriptor", nsmap={"md": md, "ds": ds}, entityID=i.metadata_entity or f"{base}/saml/{i.name}"
    )
    idp_el = etree.SubElement(root, f"{{{md}}}IDPSSODescriptor", protocolSupportEnumeration=PROTOCOL)
    for pem in (i.cert_pem, *i.previous):
        body = "".join(line for line in pem.strip().splitlines() if "CERTIFICATE" not in line)
        kd = etree.SubElement(idp_el, f"{{{md}}}KeyDescriptor", use="signing")
        x = etree.SubElement(etree.SubElement(kd, f"{{{ds}}}KeyInfo"), f"{{{ds}}}X509Data")
        etree.SubElement(x, f"{{{ds}}}X509Certificate").text = body
    etree.SubElement(
        idp_el,
        f"{{{md}}}SingleSignOnService",
        Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
        Location=f"{base}/saml/{i.name}/sso",
    )
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8")


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

    @app.get("/saml/{name}/metadata")
    async def metadata(name: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        return Response(metadata_xml(base, idp(name)), media_type="application/samlmetadata+xml")

    @app.post("/saml/{name}/rollover")
    async def rollover(name: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Signs with a new key from now on; the metadata lists the new certificate and the old one, as Entra and Okta
        do during a rollover."""
        i = idp(name)
        fresh = _new_idp(name)
        i.previous.insert(0, i.cert_pem)
        i.key, i.cert_pem = fresh.key, fresh.cert_pem
        return {"certificate": i.cert_pem}

    @app.post("/saml/{name}/expire")
    async def expire(name: str) -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        """Replaces the provider's certificate with one for the same key that ended yesterday."""
        i = idp(name)
        i.cert_pem = _certificate(name, i.key, starts=timedelta(days=-400), ends=timedelta(days=-1))
        return {"certificate": i.cert_pem}

    @app.put("/saml/{name}/metadata-entity")
    async def metadata_entity(name: str, request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """`{entityId}`: the metadata names this entity id instead (a hijacked metadata URL), with a new key."""
        i = idp(name)
        i.metadata_entity = str((await request.json())["entityId"])
        fresh = _new_idp(name)
        i.previous.insert(0, i.cert_pem)
        i.key, i.cert_pem = fresh.key, fresh.cert_pem
        return {"entityId": i.metadata_entity}

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
            # No `groups` parameter sends no attribute; `groups=` sends an empty one.
            groups=[g for g in q["groups"].split(",") if g] if "groups" in q else None,
            overage=q.get("overage") == "1",
            encrypt_to=str(known["certificate"]) if known.get("encrypt") else None,
            cipher=str(known.get("cipher", "aes256-gcm")),
            key_transport=str(known.get("keyTransport", "rsa-oaep-mgf1p")),
            sign_assertion=bool(known.get("signAssertion", True)),
            sign_response=bool(known.get("signResponse", False)),
        )
        return _post_form(acs, {"SAMLResponse": response, "RelayState": q.get("RelayState", "")})

    @app.get("/saml/{name}/unsolicited", response_class=HTMLResponse)
    async def unsolicited(name: str, user: str, acs: str, audience: str) -> str:  # pyright: ignore[reportUnusedFunction]
        """What an app-portal tile does when set to post straight to the service: a response nobody asked for."""
        i = idp(name)
        email = user.strip().lower()
        response = saml_response(
            i,
            issuer=f"{base}/saml/{name}",
            audience=audience,
            acs=acs,
            in_response_to=None,
            email=email,
            auth_time=i.login_time(email, forced=False, stale=False),
        )
        return _post_form(acs, {"SAMLResponse": response, "RelayState": ""})

    return app


def _post_form(action: str, fields: dict[str, str]) -> str:
    """The page a provider returns to post its answer to the service with the POST binding."""
    inputs = "".join(
        f'<input type="hidden" name="{k}" value="{html.escape(v, quote=True)}">' for k, v in fields.items()
    )
    return (
        f'<html><body onload="document.forms[0].submit()"><form method="post" action="{html.escape(action)}">'
        f"{inputs}</form></body></html>"
    )


def saml_response(
    i: Idp,
    *,
    issuer: str,
    audience: str,
    acs: str,
    in_response_to: str | None,
    email: str,
    auth_time: int,
    groups: list[str] | None = None,
    overage: bool = False,
    encrypt_to: str | None = None,
    cipher: str = "aes256-gcm",
    key_transport: str = "rsa-oaep-mgf1p",
    sign_assertion: bool = True,
    sign_response: bool = False,
) -> str:
    """A Response holding one assertion signed with the provider's key, base64 as the POST binding sends it. With
    `encrypt_to` (a certificate) the assertion is encrypted to it; `sign_response` signs the Response around it.
    `groups` None sends no groups attribute and [] an empty one; `overage` sends Entra's groups.link claim in its
    place, as Entra does for a person in more than 150 groups."""
    now = datetime.now(UTC)
    later = now + timedelta(minutes=5)
    response = etree.Element(
        f"{{{PROTOCOL}}}Response",
        nsmap={"samlp": PROTOCOL, "saml": ASSERTION},
        ID=f"_{secrets.token_hex(16)}",
        Version="2.0",
        IssueInstant=_iso(now),
        Destination=acs,
    )
    if in_response_to is not None:
        response.set("InResponseTo", in_response_to)
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
    confirmation = etree.SubElement(
        sc, f"{{{ASSERTION}}}SubjectConfirmationData", Recipient=acs, NotOnOrAfter=_iso(later)
    )
    if in_response_to is not None:
        confirmation.set("InResponseTo", in_response_to)
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
    if overage:
        attr = etree.SubElement(attrs, f"{{{ASSERTION}}}Attribute", Name=GROUPS_OVERAGE)
        etree.SubElement(attr, f"{{{ASSERTION}}}AttributeValue").text = "https://graph.microsoft.com/v1.0/me/memberOf"
    elif groups is not None:
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
