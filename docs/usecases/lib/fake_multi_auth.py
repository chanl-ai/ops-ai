"""A fake system for every sign-in method a plugin can use (c-588): one endpoint per method, each accepting only its own
credential in the format real APIs use, and a listener that demands a client certificate.

`api.multi.test` serves the API and `login.multi.test` fronts navikt's mock-oauth2-server (the OAuth server the fake
Salesforce runs, `fake_salesforce.oauth_server`). Both answer on https on this machine's private address with one
self-signed certificate. The login host checks each token request's client before passing it on, as a real
authorization server does: a client it does not know, or a wrong secret, gets `invalid_client` with 401, whether the
client is sent in the form or as basic auth. `mtls.bank.test` (bank_certificates.py) answers only a TLS handshake that
presents a client certificate its CA signed. tools-service reaches all three as any outside system: the use case lists
the hosts and the private range, trusts the API's certificate (OPS_EGRESS_CA_FILE), maps the names to the addresses and
ports (OPS_EGRESS_RESOLVE, dev only), and gives the certificate listener's CA to the connection as its trusted server
certificate.

Each endpoint answers one record naming the method and whose credential it carried. The fake keeps, per call, the
method and a short digest of the credential it received, never the credential, so a use case can print what the fake
saw. A control expires every token issued so far, so a use case can prove a call renews its token.

Run as a script, it serves until stdin closes and prints one JSON line with what a Node ui use case needs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import socket
import ssl
import sys
import tempfile
import threading
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from bank_certificates import MTLS_HOST
from bank_certificates import make as bank_certificates
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address
from fake_salesforce import AUDIENCE, ISSUER_ID, oauth_server
from fake_salesforce import _serve as serve_https  # pyright: ignore[reportPrivateUsage]

LOGIN_HOST = "login.multi.test"
API_HOST = "api.multi.test"
ISSUER = f"https://{LOGIN_HOST}/{ISSUER_ID}"
KEY_HEADER = "X-Desk-Key"
KEY_PARAM = "api_key"
# The credentials the fake accepts. They are made-up values for a fake system, so a use case may hold them in code.
SECRETS = {
    "key": "desk-key-5b1e9c0d7a",
    "username": "harbor-integration",
    "password": "pw-3f8a61c2e4",
    "token": "static-token-9d27e0b4c1",
}
# OAuth clients the login host knows: one for client credentials, one for each person's sign-in.
CLIENTS = {"multi-cc": "cc-secret-71b3e5a8d2", "multi-app": "app-secret-c49f0a2e6b"}
RECORD = {"id": "rec-1042", "title": "Harbor ticket 1042", "status": "open"}


def digest(value: str) -> str:
    """Eight hex digits naming a credential, so a record of what the fake received shows which one without its value."""
    return hashlib.sha256(value.encode()).hexdigest()[:8]


def _certificate(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake multi-auth system")])
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
    cert_file, key_file = folder / "multi.crt", folder / "multi.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


def _client_of(form: dict[str, list[str]], authorization: str) -> tuple[str, str]:
    """The client a token request names: from basic auth when it is sent so, else from the form (RFC 6749 2.3.1)."""
    if authorization.lower().startswith("basic "):
        pair = base64.b64decode(authorization[6:]).decode()
        cid, _, secret = pair.partition(":")
        return cid, secret
    return form.get("client_id", [""])[0], form.get("client_secret", [""])[0]


class MultiAuth:
    """What each call carried and the tokens issued, kept for checks; the API checks each method's credential."""

    def __init__(self, upstream: str) -> None:
        self.upstream = upstream
        # One row per API call: method, whether its credential was accepted, a digest of it, and whose it was.
        self.calls: list[dict[str, Any]] = []
        # One row per token request the login host saw: grant, client id, and whether the client was accepted.
        self.token_requests: list[dict[str, Any]] = []
        self._issued: set[str] = set()
        self._expired: set[str] = set()
        self._jwks = jwt.PyJWKClient(f"{upstream}/{ISSUER_ID}/jwks")

    def expire(self) -> None:
        """Every token issued so far is refused from now on, as when its lifetime ends; a new one is accepted."""
        self._expired |= self._issued

    def app(self) -> Any:
        from starlette.applications import Starlette  # noqa: PLC0415 - the agents-service environment has it
        from starlette.routing import Route  # noqa: PLC0415

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST"])])

    def mtls_app(self) -> Any:
        """The certificate listener: the TLS handshake already refused anyone without a certificate the CA signed."""
        from starlette.applications import Starlette  # noqa: PLC0415
        from starlette.responses import JSONResponse  # noqa: PLC0415
        from starlette.routing import Route  # noqa: PLC0415

        async def cert(_request: Any) -> Any:
            self.calls.append({"method": "cert", "accepted": True, "as": "certificate"})
            return JSONResponse({"method": "cert", "as": "certificate", "record": RECORD})

        return Starlette(routes=[Route("/cert", cert, methods=["GET"]), Route("/cert/{rest:path}", cert)])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse  # noqa: PLC0415

        host = (request.headers.get("host") or "").split(":")[0]
        body = await request.body()
        path = request.url.path
        if path.startswith("/_control/"):
            if request.method == "POST" and path == "/_control/expire":
                self.expire()
            return JSONResponse(self.state())
        if host == LOGIN_HOST:
            return await self._login(request, body)
        method = path.strip("/").split("/", 1)[0]
        check = {
            "open": self._open,
            "header-key": self._header_key,
            "query-key": self._query_key,
            "basic": self._basic,
            "bearer": self._bearer,
            "cc": self._oauth,
            "person": self._oauth,
        }.get(method)
        if check is None:
            return JSONResponse({"error": "not_found", "message": path}, 404)
        accepted, given, who = check(request)
        self.calls.append({"method": method, "accepted": accepted, "credential": digest(given) if given else None})
        if not accepted:
            # The way most APIs refuse a missing or wrong credential: 401 with a WWW-Authenticate challenge.
            tokens = method in ("bearer", "cc", "person")
            challenge = 'Bearer error="invalid_token"' if tokens else 'Basic realm="multi"'
            return JSONResponse(
                {"error": "unauthorized", "message": "The credential was refused."},
                401,
                headers={"WWW-Authenticate": challenge},
            )
        self.calls[-1]["as"] = who
        if path.endswith("/echo"):
            # Some systems repeat the request they were sent; a plugin tool that returns this must not leak the sign-in.
            return JSONResponse({"method": method, "sent": dict(request.headers)})
        return JSONResponse({"method": method, "as": who, "record": RECORD})

    @staticmethod
    def _open(_request: Any) -> tuple[bool, str, str]:
        return True, "", "anyone"

    @staticmethod
    def _header_key(request: Any) -> tuple[bool, str, str]:
        given = request.headers.get(KEY_HEADER, "")
        return given == SECRETS["key"], given, "team"

    @staticmethod
    def _query_key(request: Any) -> tuple[bool, str, str]:
        given = request.query_params.get(KEY_PARAM, "")
        return given == SECRETS["key"], given, "team"

    @staticmethod
    def _basic(request: Any) -> tuple[bool, str, str]:
        auth = request.headers.get("authorization", "")
        if not auth.startswith("Basic "):
            return False, auth, ""
        user, _, password = base64.b64decode(auth[6:]).decode().partition(":")
        ok = user == SECRETS["username"] and password == SECRETS["password"]
        return ok, password, user

    @staticmethod
    def _bearer(request: Any) -> tuple[bool, str, str]:
        auth = request.headers.get("authorization", "")
        given = auth[7:] if auth.startswith("Bearer ") else ""
        return given == SECRETS["token"], given, "team"

    def _oauth(self, request: Any) -> tuple[bool, str, str]:
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        if not token or token in self._expired:
            return False, token, ""
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
        except jwt.PyJWTError:
            return False, token, ""
        # A person's token names them in `sub`; a client's token (client credentials) names no person.
        return True, token, str(claims.get("sub") or "client")

    async def _login(self, request: Any, body: bytes) -> Any:
        from starlette.responses import JSONResponse, Response  # noqa: PLC0415

        path = request.url.path
        if path.endswith("/token"):
            form = parse_qs(body.decode())
            cid, secret = _client_of(form, request.headers.get("authorization", ""))
            grant = form.get("grant_type", [""])[0]
            ok = cid in CLIENTS and secret == CLIENTS[cid]
            self.token_requests.append({"grant": grant, "client": cid, "accepted": ok})
            if not ok:
                return JSONResponse(
                    {"error": "invalid_client", "error_description": "Client authentication failed."}, 401
                )
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        headers |= {"Host": LOGIN_HOST, "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443"}
        async with httpx.AsyncClient() as c:
            r = await c.request(
                request.method,
                f"{self.upstream}{path}?{request.url.query}",
                content=body,
                headers=headers,
                follow_redirects=False,
            )
        if path.endswith("/token") and r.status_code == 200:
            answer = r.json()
            self._issued.add(str(answer.get("access_token")))
            return JSONResponse(answer, 200)
        out = {
            k: v
            for k, v in r.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")
        }
        return Response(r.content, status_code=r.status_code, headers=out)

    def state(self) -> dict[str, Any]:
        return {"calls": list(self.calls), "token_requests": list(self.token_requests)}


@contextmanager
def multi_auth(token_expiry_s: int = 300) -> Generator[dict[str, Any]]:
    """The fake on https, the OAuth server behind it and the certificate listener. Yields tools-service's settings to
    reach them, the hosts and range to list, the API and listener bases, the OAuth addresses, the credentials it
    accepts, the certificate listener's CA and a client certificate it accepts (as PEM text), `fake` (its state), and
    `sign_in(url, username)`, which plays a person's browser through the sign-in page and returns the code and state."""
    import uvicorn  # noqa: PLC0415

    with oauth_server(token_expiry_s) as upstream, tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        cert, key = _certificate(folder)
        bank = bank_certificates(folder)
        address = private_address()
        fake = MultiAuth(upstream)
        server, port = serve_https(fake.app(), address, cert, key)
        with socket.socket() as s:
            s.bind((address, 0))
            mtls_port = int(s.getsockname()[1])
        mtls = uvicorn.Server(
            uvicorn.Config(
                fake.mtls_app(),
                host=address,
                port=mtls_port,
                log_level="warning",
                ssl_certfile=str(bank["server_cert"]),
                ssl_keyfile=str(bank["server_key"]),
                ssl_ca_certs=str(bank["ca"]),
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                # TLS 1.2, as fake_bank_serve.py serves it: a missing certificate is then refused in the handshake.
                # Under TLS 1.3 the refusal comes after it and reaches a client as a reset, not a TLS failure.
                ssl_version=ssl.PROTOCOL_TLSv1_2,
            )
        )
        threading.Thread(target=mtls.run, daemon=True).start()
        for _ in range(100):
            if mtls.started:
                break
            time.sleep(0.1)
        try:

            def sign_in(authorize_url: str, username: str) -> dict[str, str]:
                url = urlsplit(authorize_url)
                target = f"https://{address}:{port}{url.path}?{url.query}"
                # Reached by address with the sign-in host named in Host; tools-service, which verifies the name,
                # reaches the same certificate by name through OPS_EGRESS_RESOLVE.
                with httpx.Client(verify=False, headers={"Host": LOGIN_HOST}, timeout=30) as browser:
                    page = browser.get(target)
                    if page.status_code != 200:
                        return {"error": f"sign-in page {page.status_code}"}
                    posted = browser.post(target, data={"username": username, "claims": ""}, follow_redirects=False)
                back = parse_qs(urlsplit(posted.headers.get("location", "")).query)
                return {k: v[0] for k, v in back.items()}

            yield {
                "settings": {
                    "OPS_EGRESS_CA_FILE": str(cert),
                    "OPS_EGRESS_RESOLVE": json.dumps(
                        {
                            LOGIN_HOST: f"{address}:{port}",
                            API_HOST: f"{address}:{port}",
                            MTLS_HOST: f"{address}:{mtls_port}",
                        }
                    ),
                },
                "hosts": [LOGIN_HOST, API_HOST, MTLS_HOST],
                "range": f"{address}/32",
                "api_base": f"https://{API_HOST}",
                "mtls_base": f"https://{MTLS_HOST}",
                "login_base": f"https://{LOGIN_HOST}/{ISSUER_ID}",
                "token_url": f"{ISSUER}/token",
                "authorize_url": f"{ISSUER}/authorize",
                "control": f"https://{address}:{port}/_control",
                "secrets": dict(SECRETS),
                "clients": dict(CLIENTS),
                "mtls_ca": bank["ca"].read_text(),
                "client_cert": bank["client_cert"].read_text(),
                "client_key": bank["client_key"].read_text(),
                "ca": str(cert),
                "fake": fake,
                "sign_in": sign_in,
            }
        finally:
            mtls.should_exit = True
            server.should_exit = True


if __name__ == "__main__":
    # A parent that stops this script with SIGTERM still gets the OAuth server's container removed: SystemExit runs the
    # context managers' cleanup, which the default SIGTERM action skips.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with multi_auth() as m:
        shown = {k: v for k, v in m.items() if k not in ("fake", "sign_in", "client_key")}
        print(json.dumps({**shown, "owner": os.getpid()}), flush=True)
        sys.stdin.read()
