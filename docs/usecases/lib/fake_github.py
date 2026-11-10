"""A fake GitHub at two sign-in hosts, for use cases that show several accounts of an app that is not Salesforce.

`github.test` and `ghe.corp.test` each serve GitHub's OAuth sign-in (`/login/oauth/authorize`, which sends the browser
back with a code at once, and `/login/oauth/access_token`), and `api.github.test` serves the REST API the GitHub
plugin calls (`/user`, `/repos/{owner}/{repo}/issues`). A token is good only at the API and names the sign-in host
that issued it, so the API answers each account with the issue of the server it signed in to: a call that used the
wrong account shows the other server's issue. The plugin declares no `connection.identity` and fills nothing from the
token answer, which is why the use cases use it.

All three answer on https on this machine's private address with one self-signed certificate; tools-service reaches
them as any outside system (OPS_EGRESS_CA_FILE, OPS_EGRESS_RESOLVE, the private range listed by Security).
"""

from __future__ import annotations

import json
import tempfile
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address
from fake_salesforce import _serve as serve_https  # pyright: ignore[reportPrivateUsage]

PUBLIC, CORP, API = "github.test", "ghe.corp.test", "api.github.test"
# The one issue each server holds, so an answer names the server the call's account signed in to.
ISSUES = {
    PUBLIC: {"number": 7, "title": "Retry the payout export", "state": "open"},
    CORP: {"number": 412, "title": "Rotate the branch office VPN keys", "state": "open"},
}
# Who signs in at each server, as GitHub's /user names them.
LOGINS = {PUBLIC: "mokafor", CORP: "maya.okafor"}


def _certificate(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake github")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(h) for h in (PUBLIC, CORP, API)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / "github.crt", folder / "github.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


class GitHub:
    def __init__(self) -> None:
        self._codes: dict[str, str] = {}
        self._tokens: dict[str, str] = {}
        # Every API call answered: the server whose token it carried and the path.
        self.calls: list[dict[str, str]] = []
        # Every sign-in host that issued a token.
        self.issued: list[str] = []

    def app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.routing import Route

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST"])])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse, RedirectResponse

        host = (request.headers.get("host") or "").split(":")[0]
        path = request.url.path
        if host in ISSUES and path == "/login/oauth/authorize":
            q = request.query_params
            code = uuid.uuid4().hex
            self._codes[code] = host
            back = f"{q.get('redirect_uri', '')}?{urlencode({'code': code, 'state': q.get('state', '')})}"
            return RedirectResponse(back, status_code=302)
        if host in ISSUES and path == "/login/oauth/access_token":
            form = parse_qs((await request.body()).decode())
            issuer = self._codes.pop(form.get("code", [""])[0], None)
            if issuer != host:
                return JSONResponse({"error": "bad_verification_code"}, 200)
            token = f"gho_{uuid.uuid4().hex}"
            self._tokens[token] = host
            self.issued.append(host)
            return JSONResponse({"access_token": token, "token_type": "bearer", "scope": "repo,read:user"})
        if host != API:
            return JSONResponse({"message": "Not Found"}, 404)
        auth = request.headers.get("authorization", "")
        server = self._tokens.get(auth.split(" ", 1)[1] if " " in auth else "")
        if server is None:
            return JSONResponse({"message": "Bad credentials"}, 401)
        self.calls.append({"server": server, "path": path})
        if path == "/user":
            return JSONResponse({"login": LOGINS[server], "id": 1})
        if path.endswith("/issues"):
            issue = ISSUES[server]
            return JSONResponse(
                [
                    {
                        **issue,
                        "user": {"login": LOGINS[server]},
                        "labels": [],
                        "updated_at": "2026-11-09T09:00:00Z",
                        "html_url": f"https://{server}/brightloop/dispatch/issues/{issue['number']}",
                    }
                ]
            )
        return JSONResponse({"message": "Not Found"}, 404)

    def state(self) -> dict[str, Any]:
        return {"calls": list(self.calls), "issued": list(self.issued)}


@contextmanager
def github() -> Generator[dict[str, Any]]:
    """The fake on https; yields tools-service's settings to reach it, the range to list, each server's sign-in address
    (`public_url`, `corp_url`), the API's (`api_url`), `fake`, and `sign_in(url)`, which plays the browser through a
    sign-in and returns the code and state it was sent back with."""
    with tempfile.TemporaryDirectory() as tmp:
        cert, key = _certificate(Path(tmp))
        address = private_address()
        fake = GitHub()
        server, port = serve_https(fake.app(), address, cert, key)
        try:

            def sign_in(authorize_url: str) -> dict[str, str]:
                url = urlsplit(authorize_url)
                target = f"https://{address}:{port}{url.path}?{url.query}"
                with httpx.Client(verify=False, headers={"Host": url.hostname or PUBLIC}, timeout=30) as browser:
                    sent = browser.get(target, follow_redirects=False)
                back = parse_qs(urlsplit(sent.headers.get("location", "")).query)
                return {k: v[0] for k, v in back.items()}

            yield {
                "settings": {
                    "OPS_EGRESS_CA_FILE": str(cert),
                    "OPS_EGRESS_RESOLVE": json.dumps(dict.fromkeys((PUBLIC, CORP, API), f"{address}:{port}")),
                },
                "range": f"{address}/32",
                "public_url": f"https://{PUBLIC}",
                "corp_url": f"https://{CORP}",
                "api_url": f"https://{API}",
                "issues": ISSUES,
                "logins": LOGINS,
                "fake": fake,
                "sign_in": sign_in,
            }
        finally:
            server.should_exit = True
