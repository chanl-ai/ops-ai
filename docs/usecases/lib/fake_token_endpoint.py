"""A fake sign-in for apps that prove themselves with a certificate: a Microsoft Entra style token endpoint
that takes a signed client assertion (RFC 7523 2.2) and no client secret, and Google and DocuSign style endpoints
whose grant is the signed JWT itself (RFC 7523 2.1), with an API that answers only their tokens.

Each assertion is checked as Entra checks one: the algorithm pinned by the registered key's type (RS256 for RSA, ES256
for P-256), `none` refused, the signature against the registered certificate's public key, `x5t#S256` equal to that
certificate's thumbprint, `aud` the endpoint's own token address (DocuSign: its account host), `iss` and `sub` the
client id, `nbf` not in the future, a lifetime of ten minutes or less, and a `jti` not seen before. A refusal answers
401 `invalid_client` (`invalid_grant` for a JWT grant) naming the check that failed.

The same endpoint signs a person in with a code (RFC 6749 4.1) for an app registered with a client secret
(`secret_apps`): `authorize` is the sign-in page's answer, a one-time code bound to the client, the redirect address
and the PKCE challenge (S256 only); the token request must send the client's secret (form or basic), the same redirect
address and the verifier. The answer carries a refresh token, which a `refresh_token` grant spends once. The fake records each token
request's form with the assertion's signature cut off, so a use case can print what it received without a credential.

`login.certs.test` and `api.certs.test` answer on https on this machine's private address with one self-signed
certificate; tools-service reaches them as any outside system (OPS_EGRESS_CA_FILE, OPS_EGRESS_RESOLVE), as
fake_multi_auth.py describes. The fake makes the key pairs the apps are registered with and one pair no app is, so a
use case uploads the right one or the wrong one.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import tempfile
import time
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode

import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address
from fake_multi_auth import _client_of as client_of  # pyright: ignore[reportPrivateUsage]
from fake_salesforce import _serve as serve_https  # pyright: ignore[reportPrivateUsage]

LOGIN_HOST = "login.certs.test"
API_HOST = "api.certs.test"
CLIENT_ASSERTION = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
JWT_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"
DOCUSIGN_AUDIENCE = "account-d.docusign.com"
LONGEST = 600
RECORD = {"id": "agr-2207", "title": "Card services agreement", "status": "signed"}


@dataclass
class Pair:
    key: str
    cert: str
    thumbprint: str
    alg: str
    public: Any


def make_pair(name: str, kind: str = "rsa", days: int = 365) -> Pair:
    key: Any = rsa.generate_private_key(public_exponent=65537, key_size=2048) if kind == "rsa" else (
        ec.generate_private_key(ec.SECP256R1())
    )  # fmt: skip
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=days))
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return Pair(
        key=pem.decode(),
        cert=cert.public_bytes(serialization.Encoding.PEM).decode(),
        thumbprint=base64.urlsafe_b64encode(hashlib.sha256(der).digest()).rstrip(b"=").decode(),
        alg="RS256" if kind == "rsa" else "ES256",
        public=key.public_key(),
    )


class Refused(Exception):
    """An assertion the endpoint refuses; the message names the check, never the assertion."""


class ClientRefused(Refused):
    """A code or refresh grant whose client did not prove itself with its secret: `invalid_client`, 401."""


def s256(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def _header(token: str) -> dict[str, Any]:
    try:
        head = token.split(".", maxsplit=1)[0]
        found: Any = json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
    except (ValueError, IndexError) as e:
        raise Refused("not a JWT") from e
    if not isinstance(found, dict):
        raise Refused("not a JWT")
    return dict(found)  # pyright: ignore[reportUnknownArgumentType]


class Registry:
    """The apps the endpoints know, by client id, and every assertion id already used."""

    def __init__(self) -> None:
        self.apps: dict[str, Pair] = {}
        self.seen: set[str] = set()

    def check(
        self, token: str, *, client_id: str, audience: str, subject: str | None, pin_thumbprint: bool = True
    ) -> dict[str, Any]:
        """The claims of an assertion that passes every check, else Refused naming the first that failed."""
        app = self.apps.get(client_id)
        if app is None:
            raise Refused(f"unknown client {client_id}")
        header = _header(token)
        if header.get("alg") != app.alg:
            # The algorithm comes from the registered key, never from the token: `none` and a swapped one both fail.
            raise Refused(f"algorithm {header.get('alg')} is not the registered key's {app.alg}")
        if pin_thumbprint and header.get("x5t#S256") != app.thumbprint:
            raise Refused("x5t#S256 is not the registered certificate's thumbprint")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                app.public,
                algorithms=[app.alg],
                audience=audience,
                issuer=client_id,
                options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti"]},
            )
        except jwt.InvalidSignatureError as e:
            raise Refused("the signature is not the registered certificate's") from e
        except jwt.ExpiredSignatureError as e:
            raise Refused("the assertion expired") from e
        except jwt.ImmatureSignatureError as e:
            raise Refused("the assertion is not valid yet (nbf)") from e
        except jwt.InvalidAudienceError as e:
            raise Refused(f"the audience is not {audience}") from e
        except jwt.PyJWTError as e:
            raise Refused(f"the assertion does not read ({type(e).__name__})") from e
        if subject is not None and claims.get("sub") != subject:
            raise Refused(f"the subject is not {subject}")
        if int(claims["exp"]) - int(claims["iat"]) > LONGEST:
            raise Refused("the assertion lives longer than ten minutes")
        if claims["jti"] in self.seen:
            raise Refused("the assertion was already used (replay)")
        self.seen.add(str(claims["jti"]))
        return claims


class TokenEndpoint:
    """Entra, Google and DocuSign style token endpoints and an API, each keeping what it saw."""

    def __init__(self, token_base: str) -> None:
        self.registry = Registry()
        self.token_base = token_base
        # One row per token request: the endpoint, its grant, the form's field names, and accepted or the reason.
        self.token_requests: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self._issued: dict[str, str] = {}
        # Apps that sign a person in with a code, by client id: the secret each was registered with.
        self.secret_apps: dict[str, str] = {}
        self._codes: dict[str, dict[str, str]] = {}
        self._refresh: dict[str, str] = {}

    def token_url(self, system: str) -> str:
        return f"{self.token_base}/{system}/token"

    def authorize(self, query: dict[str, str], who: str) -> str:
        """Where the sign-in page sends the browser once `who` signs in: the redirect address with a one-time code and
        the state, or with `invalid_request` for a client it does not know or a request without an S256 challenge."""
        back, state = query.get("redirect_uri", ""), query.get("state", "")
        joined = "&" if "?" in back else "?"
        ok = query.get("client_id") in self.secret_apps and query.get("response_type") == "code"
        if not ok or query.get("code_challenge_method") != "S256" or not query.get("code_challenge"):
            return f"{back}{joined}{urlencode({'error': 'invalid_request', 'state': state})}"
        code = f"code-{secrets.token_hex(12)}"
        self._codes[code] = {
            "client_id": query["client_id"], "redirect_uri": back, "challenge": query["code_challenge"], "who": who,
        }  # fmt: skip
        return f"{back}{joined}{urlencode({'code': code, 'state': state})}"

    def whose(self, authorization: str) -> str | None:
        """Who the bearer token in an Authorization header was issued to; None for a token this endpoint never issued."""
        return self._issued.get(authorization[7:]) if authorization.startswith("Bearer ") else None

    def app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.routing import Route

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST"])])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse

        host = (request.headers.get("host") or "").split(":")[0]
        path = request.url.path
        if host == LOGIN_HOST and path.endswith("/token"):
            form = {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}
            return self._token(path.strip("/").split("/")[0], form)
        auth = request.headers.get("authorization", "")
        who = self._issued.get(auth[7:]) if auth.startswith("Bearer ") else None
        self.calls.append({"path": path, "as": who})
        if who is None:
            return JSONResponse({"error": "unauthorized"}, 401, headers={"WWW-Authenticate": "Bearer"})
        return JSONResponse({"as": who, "record": RECORD})

    def _token(self, system: str, form: dict[str, str]) -> Any:
        from starlette.responses import JSONResponse

        status, body = self.token(system, form)
        return JSONResponse(body, status)

    def token(self, system: str, form: dict[str, str], authorization: str = "") -> tuple[int, dict[str, Any]]:
        """One token request's answer, also for a use case that checks the fake's refusals without a client."""
        row: dict[str, Any] = {"system": system, "grant": form.get("grant_type"), "fields": sorted(form)}
        self.token_requests.append(row)
        refresh: dict[str, str] = {}
        try:
            if form.get("grant_type") in ("authorization_code", "refresh_token"):
                who = self._code_grant(form, authorization)
                refresh["refresh_token"] = f"rt-{secrets.token_hex(12)}"
                self._refresh[refresh["refresh_token"]] = who
            elif system == "entra":
                who = self._entra(form)
            elif system in ("google", "docusign"):
                who = self._jwt_grant(system, form)
            else:
                raise Refused(f"no token endpoint {system}")
        except Refused as e:
            row["refused"] = str(e)
            coded = form.get("grant_type") in ("authorization_code", "refresh_token")
            client = isinstance(e, ClientRefused) or (system == "entra" and not coded)
            code = "invalid_client" if client else "invalid_grant"
            return (401 if client else 400), {"error": code, "error_description": str(e)}
        row["accepted"] = True
        token = f"at-{secrets.token_hex(8)}"
        self._issued[token] = who
        return 200, {"access_token": token, "token_type": "Bearer", "expires_in": 3600, **refresh}

    def _code_grant(self, form: dict[str, str], authorization: str) -> str:
        """Whom a code or refresh grant signs in, else Refused naming the check that failed."""
        client, secret = client_of({k: [v] for k, v in form.items()}, authorization)
        held = self.secret_apps.get(client)
        if held is None or not hmac.compare_digest(secret, held):
            raise ClientRefused(f"client {client} did not prove itself with its secret")
        if form["grant_type"] == "refresh_token":
            who = self._refresh.pop(form.get("refresh_token", ""), None)
            if who is None:
                raise Refused("the refresh token is unknown or was already used")
            return who
        code = self._codes.pop(form.get("code", ""), None)
        if code is None:
            raise Refused("the code is unknown or was already used")
        if code["client_id"] != client:
            raise Refused("the code was issued to another client")
        if code["redirect_uri"] != form.get("redirect_uri"):
            raise Refused("the redirect address is not the one the code was issued for")
        if s256(form.get("code_verifier", "")) != code["challenge"]:
            raise Refused("the code verifier does not match the code challenge (PKCE)")
        return code["who"]

    def _entra(self, form: dict[str, str]) -> str:
        if "client_secret" in form:
            raise Refused("a client secret was sent; this app takes its certificate only")
        if form.get("client_assertion_type") != CLIENT_ASSERTION:
            raise Refused("no client assertion")
        client_id = form.get("client_id", "")
        self.registry.check(
            form.get("client_assertion", ""), client_id=client_id, audience=self.token_url("entra"), subject=client_id
        )
        return client_id

    def _jwt_grant(self, system: str, form: dict[str, str]) -> str:
        if form.get("grant_type") != JWT_GRANT:
            raise Refused(f"grant {form.get('grant_type')} is not the JWT grant")
        if "client_secret" in form:
            raise Refused("a client secret was sent with a JWT grant")
        token = form.get("assertion", "")
        issuer = (
            str(jwt.decode(token, options={"verify_signature": False}).get("iss", "")) if token.count(".") == 2 else ""
        )
        audience = self.token_url("google") if system == "google" else DOCUSIGN_AUDIENCE
        # A Google service account's grant names no subject; DocuSign's names the user it acts for.
        claims = self.registry.check(
            token, client_id=issuer, audience=audience, subject=None, pin_thumbprint=system == "docusign"
        )
        if system == "docusign" and not claims.get("sub"):
            raise Refused("a DocuSign grant names the user it acts for")
        if system == "google" and not claims.get("scope"):
            raise Refused("a Google grant carries its scopes as a claim")
        return str(claims.get("sub") or issuer)

    def state(self) -> dict[str, Any]:
        return {"token_requests": list(self.token_requests), "calls": list(self.calls)}


def _tls(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake certificate sign-in")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(LOGIN_HOST), x509.DNSName(API_HOST)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / "certs.crt", folder / "certs.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


@contextmanager
def token_endpoint() -> Generator[dict[str, Any]]:
    """The fake on https. Yields tools-service's settings to reach it, the hosts and range to list, the API base, each
    system's token address and client id, the pair each app is registered with, a pair no app is, and `fake`."""
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = _tls(Path(tmp))
        address = private_address()
        fake = TokenEndpoint(f"https://{LOGIN_HOST}")
        apps = {
            "entra": ("ops-ai-acme-app", make_pair("ops-ai-acme-app")),
            "google": ("svc-records@acme-ops.iam.test", make_pair("svc-records")),
            "docusign": ("ds-integration-7f31", make_pair("ds-integration", "p256")),
        }
        for client_id, pair in apps.values():
            fake.registry.apps[client_id] = pair
        server, port = serve_https(fake.app(), address, cert, key)
        try:
            yield {
                "settings": {
                    "OPS_EGRESS_CA_FILE": str(cert),
                    "OPS_EGRESS_RESOLVE": json.dumps({LOGIN_HOST: f"{address}:{port}", API_HOST: f"{address}:{port}"}),
                },
                "hosts": [LOGIN_HOST, API_HOST],
                "range": f"{address}/32",
                "api_base": f"https://{API_HOST}",
                "systems": {
                    s: {"token_url": fake.token_url(s), "client_id": cid, "pair": pair}
                    for s, (cid, pair) in apps.items()
                },
                "unregistered": make_pair("ops-ai-acme-app"),
                "fake": fake,
                "started": time.time(),
            }
        finally:
            server.should_exit = True


if __name__ == "__main__":
    # Run as a script for a Node ui use case (uc-580): serves until stdin closes and prints one JSON line with the
    # settings tools-service needs, the hosts and range to list, and the Entra app's id and its registered pair.
    import signal
    import sys

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with token_endpoint() as m:
        entra = m["systems"]["entra"]
        pair = entra["pair"]
        shown = {
            "settings": m["settings"],
            "hosts": m["hosts"],
            "range": m["range"],
            "entra": {
                "clientId": entra["client_id"],
                "cert": pair.cert,
                "key": pair.key,
                "thumbprint": pair.thumbprint,
            },
        }
        print(json.dumps(shown), flush=True)
        sys.stdin.read()
