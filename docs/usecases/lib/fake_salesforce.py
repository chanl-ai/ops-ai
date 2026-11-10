"""A fake Salesforce for per-person sign-in use cases: its sign-in served by navikt's mock-oauth2-server, a
standard OAuth 2.0 server run in Docker, and a REST API that accepts only that server's tokens.

Both answer on https on this machine's private address with one self-signed certificate: `login.salesforce.test`
fronts the OAuth server and `kestrel.my.salesforce.test` serves the API, as a company's My Domain does. tools-service
reaches them as any outside system: the use case lists the hosts and the private range, gives tools-service the
certificate as its CA (OPS_EGRESS_CA_FILE) and maps the names to the address and port (OPS_EGRESS_RESOLVE, dev only).

The API checks each bearer token's signature against the server's published keys, its issuer, audience and expiry, and
records the token's subject as the editor of a case, so a use case can tell whose account a call used. The token
answer carries the scopes asked for at sign-in, as Salesforce's does, and an operation that needs a scope the token was
not granted is refused with 403.

Beside the cases it also holds an advisor's org (`Org`): Dana Whitfield's clients, contacts, opportunities, tasks,
today's meetings and an open case, answered by a small SOQL evaluator, the REST record calls, describe, composite and
SOSL, so an assistant can prep a client meeting and log what came of it, and a use case can read what it wrote.

Run as a script, it serves until stdin closes and prints one JSON line with what a Node ui use case needs.
"""

from __future__ import annotations

import copy
import json
import os
import re
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field as default
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address

from ops_service_kit import harness_containers

if TYPE_CHECKING:
    from starlette.responses import Response

LOGIN_HOST = "login.salesforce.test"
API_HOST = "kestrel.my.salesforce.test"
ISSUER_ID = "salesforce"
ISSUER = f"https://{LOGIN_HOST}/{ISSUER_ID}"
# A sandbox org: its own sign-in address on the same login host, and its own instance, so a use case can show a
# sandbox sign-in landing on the sandbox and production's on production, and a token from one refused by the other.
SANDBOX_ID = "sandbox"
SANDBOX_ISSUER = f"https://{LOGIN_HOST}/{SANDBOX_ID}"
SANDBOX_HOST = "kestrel--uat.sandbox.my.salesforce.test"
# A second production org, as a company with a European org beside its main one has: its own My Domain and tokens.
EU_ID = "eu"
EU_ISSUER = f"https://{LOGIN_HOST}/{EU_ID}"
EU_HOST = "kestrel-eu.my.salesforce.test"
# A lending package's loan object, installed in the EU org only, so a package app's call on the production org finds
# no such object, as Salesforce answers for a package an org never installed.
LOAN_OBJECT = "LNDK__Loan__c"
LOAN_ID = "a0LEU0000000001"
PACKAGES = {EU_HOST: {LOAN_OBJECT}}
INSTANCES = {ISSUER: API_HOST, SANDBOX_ISSUER: SANDBOX_HOST, EU_ISSUER: EU_HOST}
# Each org also signs in at its own My Domain, `https://<my domain>/services/oauth2/...`, as Salesforce's do: the path
# the server serves the org's sign-in under, by host.
MY_DOMAIN_LOGIN = {API_HOST: ISSUER_ID, SANDBOX_HOST: SANDBOX_ID, EU_HOST: EU_ID}
# The OAuth server's path prefix of each org other than production's, to its issuer.
ISSUER_BY_PATH = {f"/{SANDBOX_ID}/": SANDBOX_ISSUER, f"/{EU_ID}/": EU_ISSUER}
OAUTH = "/services/oauth2/"
AUDIENCE = "salesforce-api"
IMAGE = "ghcr.io/navikt/mock-oauth2-server:2.1.10"
API = "/services/data/v61.0"
CASE_ID = "5003000000D8cuIAAR"
# A second case the Salesforce plugin's use case works; writing it needs no extra scope, as in Salesforce.
PLUGIN_CASE_ID = "5003000000D8cuJAAR"
ARTICLES = "Knowledge__kav"
# Articles per listing page, so a listing of the three seeded articles takes two pages and one nextRecordsUrl.
PAGE_SIZE = 2
# The scope an operation that writes a case needs, beyond `api`; a token signed in without it is refused (US4).
WRITE_SCOPE = "cases.write"
# The advisor org's records are written under the scope the Salesforce plugin asks for.
ORG_WRITE_SCOPE = "api"
# One account's data for the query tools: three open escalated cases, one escalated case in the recycle bin,
# a contact, and a list view of escalated cases. The fake answers the fixed query shapes the plugin's tools send.
ACCOUNT_ID = "001300000000ACMEAA"
LIST_VIEW_ID = "00B300000000ESCAAA"
ACCOUNT = {"Id": ACCOUNT_ID, "Name": "Acme Card Services"}
CONTACT = {
    "Id": "003300000000ACMEAA",
    "Name": "Dana Okafor",
    "Email": "dana.okafor@acme.example",
    "AccountId": ACCOUNT_ID,
}
SEEDED_CASES = [
    {"Id": "5003000000E1aaaAAA", "CaseNumber": "00044901", "Subject": "Card declined abroad, Acme",
     "Status": "Escalated", "Priority": "High", "AccountId": ACCOUNT_ID, "IsDeleted": False,
     "LastModifiedDate": "2026-10-05T09:00:00.000+0000"},
    {"Id": "5003000000E2bbbAAA", "CaseNumber": "00044902", "Subject": "Card limit raised twice, Acme",
     "Status": "Escalated", "Priority": "Medium", "AccountId": ACCOUNT_ID, "IsDeleted": False,
     "LastModifiedDate": "2026-10-06T09:00:00.000+0000"},
    {"Id": "5003000000E3cccAAA", "CaseNumber": "00044903", "Subject": "Card duplicate, Acme",
     "Status": "Escalated", "Priority": "Low", "AccountId": ACCOUNT_ID, "IsDeleted": True,
     "LastModifiedDate": "2026-10-07T09:00:00.000+0000"},
    {"Id": "5003000000E4dddAAA", "CaseNumber": "00044904", "Subject": "Card replaced after fraud, Acme",
     "Status": "Escalated", "Priority": "High", "AccountId": ACCOUNT_ID, "IsDeleted": False,
     "LastModifiedDate": "2026-10-08T09:00:00.000+0000"},
]  # fmt: skip
SOSL_ESCAPED = re.compile(r"\\(.)")


def _certificate(folder: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "fake salesforce")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(h) for h in (LOGIN_HOST, *INSTANCES.values())]), critical=False
        )
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_file, key_file = folder / "salesforce.crt", folder / "salesforce.key"
    cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_file.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    return cert_file, key_file


@contextmanager
def oauth_server(token_expiry_s: int = 300) -> Generator[str]:
    """mock-oauth2-server in Docker on a free local port, its sign-in page interactive; yields its http address. Every
    token it issues names the API as its audience."""
    config = {
        "interactiveLogin": True,
        # The production org and the sandbox org each issue tokens for the API.
        "tokenCallbacks": [
            {
                "issuerId": issuer,
                "tokenExpiry": token_expiry_s,
                "requestMappings": [{"requestParam": "grant_type", "match": "*", "claims": {"aud": [AUDIENCE]}}],
            }
            for issuer in (ISSUER_ID, SANDBOX_ID, EU_ID)
        ],
    }
    name = f"uc-salesforce-idp-{uuid.uuid4().hex[:8]}"
    started = harness_containers.run(
        ["--name", name, "-p", "127.0.0.1::8080", "-e", f"JSON_CONFIG={json.dumps(config)}", IMAGE]
    )
    if started.returncode != 0:
        raise SystemExit(f"FAIL the OAuth server did not start (is Docker running?): {started.stderr.strip()[:300]}")
    try:
        port = subprocess.run(["docker", "port", name, "8080"], capture_output=True, text=True, check=True).stdout
        upstream = f"http://127.0.0.1:{port.strip().splitlines()[0].rsplit(':', 1)[1]}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{upstream}/{ISSUER_ID}/.well-known/openid-configuration", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise SystemExit(f"FAIL the OAuth server at {upstream} never answered")
        yield upstream
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True, check=False)


def with_username_claim(body: bytes) -> bytes:
    """The interactive sign-in form as a real OpenID provider would sign the person in: the name typed comes back as
    `preferred_username` too, not only as the subject, unless the form gives its own claims."""
    from urllib.parse import urlencode

    form = {k: v[0] for k, v in parse_qs(body.decode(), keep_blank_values=True).items()}
    if not form.get("username") or form.get("claims", "").strip():
        return body
    form["claims"] = json.dumps({"preferred_username": form["username"]})
    return urlencode(form).encode()


class Salesforce:
    """The front: the sign-in host proxied to the OAuth server, and the API, with what each call did kept for checks."""

    def __init__(self, upstream: str) -> None:
        self.upstream = upstream
        self.case: dict[str, Any] = {"Id": CASE_ID, "CaseNumber": "00044817", "Status": "New", "Subject": "Hail damage"}
        self.cases: dict[str, dict[str, Any]] = {
            PLUGIN_CASE_ID: {
                "Id": PLUGIN_CASE_ID,
                "CaseNumber": "00044818",
                "Status": "New",
                "Subject": "Card declined abroad",
            }
        }
        self.articles: dict[str, dict[str, Any]] = {
            a["Id"]: a
            for a in (
                {
                    "Id": "ka0001",
                    "Title": "Reset a card PIN",
                    "LastModifiedDate": "2026-10-01T09:00:00.000+0000",
                    "Body__c": "<p>A cardholder resets their PIN in the app under Card, then Reset PIN.</p>",
                    "PublishStatus": "Online",
                    "attachments": ["ka0001a"],
                },
                {
                    "Id": "ka0002",
                    "Title": "Report a lost card",
                    "LastModifiedDate": "2026-10-02T09:00:00.000+0000",
                    "Body__c": "<p>A lost card is blocked at once from Card, then Report lost.</p>",
                    "PublishStatus": "Online",
                    "attachments": [],
                },
                {
                    "Id": "ka0003",
                    "Title": "Travel notices",
                    "LastModifiedDate": "2026-10-03T09:00:00.000+0000",
                    "Body__c": "<p>Cards work abroad without a travel notice since 2025.</p>",
                    "PublishStatus": "Online",
                    "attachments": [],
                },
            )
        }
        self.attachments: dict[str, dict[str, Any]] = {
            "ka0001a": {
                "Id": "ka0001a",
                "Title": "card-pin-steps.txt",
                "LastModifiedDate": "2026-10-01T09:00:00.000+0000",
                "Body__c": "Step 1: open Card. Step 2: Reset PIN. Step 3: choose four digits.",
                "Mime__c": "text/plain",
            }
        }
        # Every SOQL query received, so a use case can read what a tool sent.
        self.queries: list[str] = []
        # The Sforce-Query-Options header each query-all call carried, and each userinfo call's caller.
        self.query_options: list[str | None] = []
        self.userinfo: list[str] = []
        # Each article or attachment read by id, so a use case can tell an unchanged article was not fetched again.
        self.fetched: list[str] = []
        # A listing's next-page locators, as Salesforce keeps a query cursor server-side.
        self._locators: dict[str, str] = {}
        # Cases the query tools read, by id; the deleted one only through queryAll.
        self.seeded: dict[str, dict[str, Any]] = {c["Id"]: dict(c) for c in SEEDED_CASES}
        # Set through /_control/mode: answer the next API request 401, answer the listing's second page 429 once,
        # or name a host outside Salesforce as the token's instance_url.
        self.fail_next: int | None = None
        self.limit_second_page = False
        self.bad_instance = False
        # Refresh grants answer invalid_grant, as Salesforce does once a refresh token is revoked: the team reconnects.
        self.refuse_refresh = False
        self.edits: list[dict[str, Any]] = []
        self.refused: list[str] = []
        # The advisor's org: its records by object and id, and the query conditions its evaluator could not read.
        self.org = Org(self.edits, self.refused, self.queries)
        self.records = self.org.records
        self.unparsed = self.org.unparsed
        self.revoked: list[str] = []
        # The OAuth app each token exchange came from, (client id, client secret): which app a team's sign-in used.
        self.clients: list[tuple[str, str]] = []
        # The scopes asked for at sign-in, by the code the server returned, then by the access token issued for it.
        self._scope_by_code: dict[str, str] = {}
        self._scope_by_token: dict[str, str] = {}
        self._pending: dict[str, str] = {}
        # The OAuth server signs each issuer's tokens with that issuer's own key.
        self._jwks = {
            ISSUER: jwt.PyJWKClient(f"{upstream}/{ISSUER_ID}/jwks"),
            SANDBOX_ISSUER: jwt.PyJWKClient(f"{upstream}/{SANDBOX_ID}/jwks"),
            EU_ISSUER: jwt.PyJWKClient(f"{upstream}/{EU_ID}/jwks"),
        }
        # Every API call an org answered, by its host, so a use case can tell which org a call reached.
        self.calls: list[dict[str, str]] = []

    def app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.routing import Route

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST", "PATCH"])])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse, Response

        host = (request.headers.get("host") or "").split(":")[0]
        body = await request.body()
        if request.url.path.startswith("/_control/"):
            if request.method == "POST":
                self._control(request.url.path, json.loads(body or b"{}"))
            return JSONResponse(self.state())
        if host == LOGIN_HOST:
            return await self._login(request, body)
        if (
            host in MY_DOMAIN_LOGIN
            and request.url.path.startswith(OAUTH)
            and not request.url.path.endswith("/userinfo")
        ):
            return await self._login(request, body, f"/{MY_DOMAIN_LOGIN[host]}/{request.url.path.removeprefix(OAUTH)}")
        signer = self._signer(request, host)
        if not isinstance(signer, tuple):
            return signer
        who, scopes = signer
        path = request.url.path
        self.calls.append({"host": host, "path": path, "who": who})
        if path == "/services/oauth2/userinfo":
            # On a My Domain this is also the sign-in host's UserInfo, which names the org's address.
            return self._userinfo(request)
        if self.fail_next is not None:
            status, self.fail_next = self.fail_next, None
            code = "REQUEST_LIMIT_EXCEEDED" if status == 429 else "INVALID_SESSION_ID"
            return JSONResponse([{"errorCode": code}], status)
        found = self._package_api(host, path)
        if found is not None:
            return found
        found = self._org_api(request, path, body, who, scopes)
        if found is not None:
            return found
        found = self._query_tools(request, path)
        if found is not None:
            return found
        if path == f"{API}/query":
            q = request.query_params.get("q", "")
            self.queries.append(q)
            if ARTICLES in q:
                return JSONResponse(self._articles_page(q, 0))
            if PLUGIN_CASE_ID in q or "00044818" in q:
                return JSONResponse({"totalSize": 1, "done": True, "records": [typed(self.cases[PLUGIN_CASE_ID])]})
            return JSONResponse({"totalSize": 1, "done": True, "records": [typed(self.case)]})
        if path.startswith(f"{API}/query/"):
            locator = path.rsplit("/", 1)[1]
            q, _, offset = locator.partition("-")
            if self.limit_second_page:
                self.limit_second_page = False
                return JSONResponse([{"errorCode": "REQUEST_LIMIT_EXCEEDED"}], 429)
            if q not in self._locators:
                return JSONResponse([{"errorCode": "INVALID_QUERY_LOCATOR", "message": "invalid query locator"}], 400)
            if q.startswith("c"):
                return JSONResponse(self._cases_page(self._locators[q], int(offset)))
            return JSONResponse(self._articles_page(self._locators[q], int(offset)))
        if path == f"{API}/limits":
            return JSONResponse({"DailyApiRequests": {"Max": 15000, "Remaining": 14990}})
        if path.startswith(f"{API}/sobjects/{ARTICLES}/") and request.method == "GET":
            item = path.rsplit("/", 1)[1]
            found = self.articles.get(item) or self.attachments.get(item)
            self.fetched.append(item)
            if found is None:
                return JSONResponse([{"errorCode": "NOT_FOUND"}], 404)
            return JSONResponse({**found, "attachments": [self.attachments[a] for a in found.get("attachments", [])]})
        if path.endswith("/describe"):
            fields = [{"name": f} for f in ("Id", "CaseNumber", "Status", "Subject")]
            return JSONResponse({"name": path.split("/")[-2], "fields": fields})
        if path.startswith(f"{API}/sobjects/Case/") and path != f"{API}/sobjects/Case/{CASE_ID}":
            return self._other_case(request, path, body, who)
        if path == f"{API}/sobjects/Case" and request.method == "POST":
            change = json.loads(body or b"{}")
            made = {"Id": f"500300000NEW{len(self.cases):04d}", **change}
            self.cases[made["Id"]] = made
            self.edits.append({"by": who, "change": change, "id": made["Id"]})
            return JSONResponse({"id": made["Id"], "success": True, "errors": []}, 201)
        if path == f"{API}/sobjects/Case/{CASE_ID}" and request.method == "GET":
            return JSONResponse(dict(self.case))
        if path == f"{API}/sobjects/Case/{CASE_ID}" and request.method == "PATCH":
            if WRITE_SCOPE not in scopes:
                self.refused.append(f"insufficient_scope:{who}")
                return JSONResponse([{"errorCode": "INSUFFICIENT_ACCESS", "message": f"needs {WRITE_SCOPE}"}], 403)
            change = json.loads(body or b"{}")
            self.case.update({k: v for k, v in change.items() if k in ("Status", "Subject", "Description")})
            self.case["LastModifiedBy"] = who
            self.edits.append({"by": who, "change": change})
            return Response(status_code=204)
        return JSONResponse([{"errorCode": "NOT_FOUND", "message": path}], 404)

    def _package_api(self, host: str, path: str) -> Response | None:
        """The loan package's object at an org that installed it (describe and one record), Salesforce's NOT_FOUND at
        one that did not; None for any other path."""
        from starlette.responses import JSONResponse

        prefix = f"{API}/sobjects/{LOAN_OBJECT}"
        if not path.startswith(prefix):
            return None
        if LOAN_OBJECT not in PACKAGES.get(host, set()):
            return JSONResponse([{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}], 404)
        if path == f"{prefix}/describe":
            fields = [{"name": f} for f in ("Id", "Name", "LNDK__Stage__c", "LNDK__Amount__c")]
            return JSONResponse({"name": LOAN_OBJECT, "custom": True, "fields": fields})
        if path == f"{prefix}/{LOAN_ID}":
            loan = {"Id": LOAN_ID, "Name": "Harbor bakery expansion", "LNDK__Stage__c": "Underwriting"}
            return JSONResponse({"attributes": {"type": LOAN_OBJECT}, **loan, "LNDK__Amount__c": 250000})
        return JSONResponse([{"errorCode": "NOT_FOUND", "message": path}], 404)

    def _signer(self, request: Any, host: str) -> tuple[str, set[str]] | Response:
        """The bearer token's subject and the scopes granted at its sign-in, or the 401 Salesforce answers."""
        from starlette.responses import JSONResponse

        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        try:
            said = str(jwt.decode(token, options={"verify_signature": False}).get("iss") or "")
            if said not in self._jwks:
                raise jwt.InvalidIssuerError(f"no org signs as {said or 'nobody'}")
            key = self._jwks[said].get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=AUDIENCE, issuer=list(INSTANCES))
            # Each org answers its own tokens only: a sandbox token at production's instance is refused, and back.
            if INSTANCES[str(claims["iss"])] != host:
                raise jwt.InvalidIssuerError(f"a token of {claims['iss']} at {host}")
        except jwt.PyJWTError as e:
            self.refused.append(type(e).__name__)
            return JSONResponse([{"errorCode": "INVALID_SESSION_ID", "message": str(e)}], 401)
        return str(claims["sub"]), set(self._scope_by_token.get(token, "").split())

    def _org_api(self, request: Any, path: str, body: bytes, who: str, scopes: set[str]) -> Response | None:
        """The advisor org's calls, or None for a path the case handlers answer. A Case call comes here only when it
        concerns the org's own records (`Org.answers`, `Org.owns_case`), so every existing case path answers as before."""
        from starlette.responses import JSONResponse, Response

        org, method = self.org, request.method
        if path in (f"{API}/query", f"{API}/queryAll"):
            q = str(request.query_params.get("q", ""))
            return JSONResponse(org.query(q, who)) if org.answers(q) else None
        if path == f"{API}/composite" and method == "POST":
            return JSONResponse(org.composite(_parsed(body), who, scopes))
        if not path.startswith(f"{API}/sobjects/"):
            return None
        parts = path.removeprefix(f"{API}/sobjects/").split("/")
        obj = org.object_name(parts[0])
        if obj is None or (obj == "Case" and not org.owns_case(parts, _parsed(body))):
            return None
        if parts[1:] == ["describe"]:
            return JSONResponse(org.describe(obj))
        if len(parts) == 1 and method == "POST":
            status, out = org.create(obj, _parsed(body), who, scopes)
        elif len(parts) == 2 and method == "GET":
            fields = [f for f in str(request.query_params.get("fields", "")).split(",") if f.strip()]
            status, out = org.get(obj, parts[1], fields)
        elif len(parts) == 2 and method == "PATCH":
            status, out = org.update(obj, parts[1], _parsed(body), who, scopes)
        else:
            return None
        return Response(status_code=204) if status == 204 else JSONResponse(out, status)

    def _query_tools(self, request: Any, path: str) -> Any:
        """The Salesforce calls the plugin's query tools make, or None for any other path."""
        from starlette.responses import JSONResponse

        params = request.query_params
        # The query tools filter cases by status; uc-564's case lookups by number keep their own answer below.
        if path in (f"{API}/query", f"{API}/queryAll") and re.search(
            r"FROM Case WHERE Status = '", params.get("q", "")
        ):
            q = params["q"] + (" ALL" if path.endswith("queryAll") else "")
            self.queries.append(params["q"])
            if path.endswith("queryAll"):
                self.query_options.append(request.headers.get("sforce-query-options"))
            return JSONResponse(self._cases_page(q, 0))
        if path == f"{API}/search":
            q = params.get("q", "")
            self.queries.append(q)
            # The plugin's own search keeps its exact shape; a search the model writes may name its own field group or
            # none before RETURNING.
            term = re.search(r"FIND \{(.*)\} IN ALL FIELDS", q) or re.search(r"FIND\s*\{((?:\\.|[^\\}])*)\}", q)
            if term is None:
                return JSONResponse([{"errorCode": "MALFORMED_SEARCH"}], 400)
            word = SOSL_ESCAPED.sub(r"\1", term.group(1)).lower()
            found = [{"attributes": {"type": "Account"}, **ACCOUNT}] if word in ACCOUNT["Name"].lower() else []
            if word in f"{CONTACT['Name']} {CONTACT['Email']}".lower():
                found.append({"attributes": {"type": "Contact"}, **CONTACT})
            found += [
                {"attributes": {"type": "Case"}, **{k: c[k] for k in ("Id", "CaseNumber", "Subject")}}
                for c in self._live()
                if word in c["Subject"].lower()
            ]
            found += self.org.search(word, q[term.end() :])
            return JSONResponse({"searchRecords": found})
        if path == f"{API}/parameterizedSearch":
            self.queries.append(str(params))
            word = SOSL_ESCAPED.sub(r"\1", params.get("q", "")).lower()
            status = re.fullmatch(r"Status = '(\w+)'", params.get("Case.where", ""))
            fields = [f for f in params.get("Case.fields", "Id").split(",") if f]
            rows = [
                c for c in self._live() if word in c["Subject"].lower() and (not status or c["Status"] == status[1])
            ]
            offset, limit = int(params.get("offset", 0)), int(params.get("overallLimit", 25))
            page = rows[offset : offset + limit]
            return JSONResponse(
                {"searchRecords": [{"attributes": {"type": "Case"}, **{f: c.get(f) for f in fields}} for c in page]}
            )
        if path == f"{API}/sobjects/Account/{ACCOUNT_ID}/Cases":
            return JSONResponse(self._cases_page(f"FROM Case WHERE AccountId = '{ACCOUNT_ID}'", 0))
        if path == f"{API}/sobjects/Case/updated/":
            start, end = _when(params.get("start", "")), _when(params.get("end", ""))
            if start is None or end is None:
                return JSONResponse([{"errorCode": "INVALID_DATE", "message": "start and end are dates"}], 400)
            if (end - start).days > 30:
                return JSONResponse([{"errorCode": "EXCEEDED_ID_LIMIT", "message": "at most 30 days"}], 400)
            # Changed records only: Salesforce lists deleted ones through getDeleted, not here.
            ids = [c["Id"] for c in self._live() if start <= _when(c["LastModifiedDate"]) <= end]  # type: ignore[operator]
            return JSONResponse({"ids": ids, "latestDateCovered": params["end"]})
        if path == f"{API}/ui-api/list-records/{LIST_VIEW_ID}":
            rows = [c for c in self._live() if c["Status"] == "Escalated"]
            at = int(str(params.get("pageToken") or "T0")[1:])
            page = rows[at : at + 1]
            out: dict[str, Any] = {
                "records": [
                    {
                        "id": c["Id"],
                        "fields": {k: {"value": c[k], "displayValue": None} for k in ("CaseNumber", "Subject")},
                    }
                    for c in page
                ],
                "nextPageToken": f"T{at + 1}" if at + 1 < len(rows) else None,
            }
            return JSONResponse(out)
        return None

    def _live(self) -> list[dict[str, Any]]:
        return sorted((c for c in self.seeded.values() if not c["IsDeleted"]), key=lambda c: c["LastModifiedDate"])

    def _cases_page(self, q: str, offset: int) -> dict[str, Any]:
        """The seeded cases a fixed case query asks for, PAGE_SIZE at a time: by status and LastModifiedDate, or by
        account; deleted ones only when the query came through queryAll."""
        rows = sorted(self.seeded.values(), key=lambda c: (c["LastModifiedDate"], c["Id"]))
        if not q.endswith(" ALL"):
            rows = [c for c in rows if not c["IsDeleted"]]
        if status := re.search(r"Status = '(\w+)'", q):
            rows = [c for c in rows if c["Status"] == status[1]]
        if since := re.search(r"LastModifiedDate > (\S+)", q):
            after = _when(since[1])
            rows = [c for c in rows if after is not None and _when(c["LastModifiedDate"]) > after]  # type: ignore[operator]
        if account := re.search(r"AccountId = '(\w+)'", q):
            rows = [c for c in rows if c["AccountId"] == account[1]]
        page = [typed(c) for c in rows[offset : offset + PAGE_SIZE]]
        out: dict[str, Any] = {"totalSize": len(rows), "done": offset + PAGE_SIZE >= len(rows), "records": page}
        if not out["done"]:
            key = f"c{len(self._locators)}"
            self._locators[key] = q
            out["nextRecordsUrl"] = f"{API}/query/{key}-{offset + PAGE_SIZE}"
        return out

    def _articles_page(self, q: str, offset: int) -> dict[str, Any]:
        """Online articles changed after the query's LastModifiedDate, PAGE_SIZE at a time; nextRecordsUrl names the
        next page while one is left, as Salesforce's query locator does."""
        since = re.search(r"LastModifiedDate > (\S+)", q)
        rows = sorted(
            (a for a in self.articles.values() if a["PublishStatus"] == "Online"),
            key=lambda a: (a["LastModifiedDate"], a["Id"]),
        )
        if since:
            stamp = since.group(1).replace("Z", "+0000").replace(".000", "")
            rows = [a for a in rows if a["LastModifiedDate"].replace(".000", "") > stamp]
        page = rows[offset : offset + PAGE_SIZE]
        out: dict[str, Any] = {
            "totalSize": len(rows),
            "done": offset + PAGE_SIZE >= len(rows),
            "records": [{k: a[k] for k in ("Id", "Title", "LastModifiedDate")} for a in page],
        }
        if not out["done"]:
            key = f"q{len(self._locators)}"
            self._locators[key] = q
            out["nextRecordsUrl"] = f"{API}/query/{key}-{offset + PAGE_SIZE}"
        return out

    def _other_case(self, request: Any, path: str, body: bytes, who: str) -> Any:
        from starlette.responses import JSONResponse, Response

        parts = path.removeprefix(f"{API}/sobjects/Case/").split("/")
        if len(parts) == 2:  # an upsert by an external key field
            key_field, key = parts
            found = next((c for c in self.cases.values() if str(c.get(key_field)) == key), None)
            change = json.loads(body or b"{}")
            if found is None:
                found = {"Id": f"500300000UPS{len(self.cases):04d}", key_field: key}
                self.cases[found["Id"]] = found
            found.update(change)
            self.edits.append({"by": who, "change": change, "id": found["Id"]})
            return JSONResponse({"id": found["Id"], "success": True, "created": False}, 200)
        case = self.cases.get(parts[0])
        if case is None:
            return JSONResponse([{"errorCode": "NOT_FOUND"}], 404)
        if request.method == "GET":
            return JSONResponse(dict(case))
        change = json.loads(body or b"{}")
        case.update(change)
        case["LastModifiedBy"] = who
        self.edits.append({"by": who, "change": change, "id": case["Id"]})
        return Response(status_code=204)

    def _control(self, path: str, body: dict[str, Any]) -> None:
        """What a use case changes: the failure modes, and articles edited or unpublished at the source."""
        if path.endswith("/mode"):
            self.fail_next = body.get("failNext")
            self.limit_second_page = bool(body.get("limitSecondPage"))
            self.bad_instance = bool(body.get("badInstance"))
            self.refuse_refresh = bool(body.get("refuseRefresh"))
            if body.get("expireLocators"):
                # Salesforce drops a query locator after a while; the next page asked of it is refused.
                self._locators.clear()
        elif path.endswith("/articles"):
            for item in body.get("change", []):
                self.articles[item["Id"]].update(item)

    async def _login(self, request: Any, body: bytes, path: str | None = None) -> Any:
        """The OAuth server, at `path` on it (the request's own, or a My Domain sign-in's mapped to its org's)."""
        from starlette.responses import JSONResponse, Response

        path = path or request.url.path
        if path.endswith("/authorize") and request.method == "POST":
            body = with_username_claim(body)
        if path.endswith("/revoke"):
            self.revoked.append(parse_qs(body.decode()).get("token", [""])[0])
            return Response(status_code=200)
        if path == "/services/oauth2/userinfo":
            return self._userinfo(request)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        headers |= {"Host": LOGIN_HOST, "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443"}
        query = str(request.url.query)
        if path.endswith("/token") and self.refuse_refresh and "grant_type=refresh_token" in body.decode():
            return JSONResponse({"error": "invalid_grant", "error_description": "expired access/refresh token"}, 400)
        if path.endswith("/authorize"):
            state = parse_qs(query).get("state", [""])[0]
            self._pending[state] = parse_qs(query).get("scope", [""])[0]
        async with httpx.AsyncClient() as c:
            r = await c.request(
                request.method, f"{self.upstream}{path}?{query}", content=body, headers=headers, follow_redirects=False
            )
        out = {
            k: v
            for k, v in r.headers.items()
            if k.lower() not in ("content-length", "transfer-encoding", "content-encoding")
        }
        if path.endswith("/authorize") and r.status_code == 302:
            back = parse_qs(urlsplit(r.headers.get("location", "")).query)
            code, state = back.get("code", [""])[0], back.get("state", [""])[0]
            self._scope_by_code[code] = self._pending.pop(state, "")
        if path.endswith("/token") and r.status_code == 200:
            form = parse_qs(body.decode())
            self.clients.append((form.get("client_id", [""])[0], form.get("client_secret", [""])[0]))
            answer = r.json()
            grant = form.get("grant_type", [""])[0]
            if grant == "authorization_code":
                scope = self._scope_by_code.pop(form.get("code", [""])[0], "")
            else:
                scope = self._scope_by_token.get(form.get("refresh_token", [""])[0], "")
            answer["scope"] = scope
            # Salesforce names the org's own address in every token answer; a plugin reads its instance from here.
            issuer = next((i for p, i in ISSUER_BY_PATH.items() if path.startswith(p)), ISSUER)
            answer["instance_url"] = "https://evil.example" if self.bad_instance else f"https://{INSTANCES[issuer]}"
            self._scope_by_token[answer["access_token"]] = scope
            if answer.get("refresh_token"):
                self._scope_by_token[answer["refresh_token"]] = scope
            return JSONResponse(answer, 200)
        return Response(r.content, status_code=r.status_code, headers=out)

    def _userinfo(self, request: Any) -> Any:
        """Salesforce's UserInfo endpoint on the sign-in host, in its format: who signed in, their org, and the org's
        addresses, its My Domain under `urls.custom_domain` (help.salesforce.com, "Using the UserInfo Endpoint")."""
        from starlette.responses import JSONResponse

        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        try:
            said = str(jwt.decode(token, options={"verify_signature": False}).get("iss") or "")
            if said not in self._jwks:
                raise jwt.InvalidIssuerError(f"no org signs as {said or 'nobody'}")
            key = self._jwks[said].get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=AUDIENCE, issuer=list(INSTANCES))
        except jwt.PyJWTError:
            return JSONResponse({"error": "invalid_token", "error_description": "Bad_OAuth_Token"}, 403)
        who = str(claims["sub"])
        self.userinfo.append(who)
        # Each org's own My Domain: a sandbox token names the sandbox's instance.
        domain = "https://evil.example" if self.bad_instance else f"https://{INSTANCES[str(claims['iss'])]}"
        # A person the advisor org holds is named by their User id, so a query on OwnerId can use what this answers.
        user = self.org.user_named(who)
        user_id = str(user["Id"]) if user else f"005{who}"
        return JSONResponse(
            {
                "sub": f"https://{LOGIN_HOST}/id/00Dkestrel/{user_id}",
                "user_id": user_id,
                "organization_id": "00Dkestrel",
                "preferred_username": who,
                "active": True,
                "user_type": "STANDARD",
                "urls": {
                    "rest": f"{domain}/services/data/v{{version}}/",
                    "query": f"{domain}/services/data/v{{version}}/query/",
                    "custom_domain": domain,
                },
            }
        )

    def state(self) -> dict[str, Any]:
        return {
            "query_options": list(self.query_options),
            "userinfo": list(self.userinfo),
            "case": dict(self.case),
            "cases": {k: dict(v) for k, v in self.cases.items()},
            "queries": list(self.queries),
            "edits": list(self.edits),
            "fetched": list(self.fetched),
            "refused": list(self.refused),
            "revoked": list(self.revoked),
            "clients": list(self.clients),
            "records": copy.deepcopy(self.records),
            "unparsed": list(self.unparsed),
            "calls": list(self.calls),
        }


def typed(case: dict[str, Any]) -> dict[str, Any]:
    """A case as a SOQL query answers it: Salesforce puts each record's type and address under `attributes`."""
    return {"attributes": {"type": "Case", "url": f"{API}/sobjects/Case/{case['Id']}"}, **case}


def _when(text: str) -> datetime | None:
    """A Salesforce or ISO date and time as UTC, or None."""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# The advisor org: Dana Whitfield of Harbor & Pine and her book of clients. The ids are fixed so a use case can name
# them; each has its object's real three-character prefix and Salesforce's 18-character form.
DANA_USERNAME = "dana.whitfield"
DANA_ID = "0058c00000HPDANAAA"
PRIYA_ID = "0058c00000HPPRIYAA"
OKAFOR_ID = "0018c00000OKAFORAA"
LINDQVIST_ID = "0018c00000LINDQVAA"
GRACE_ID = "0038c00000GRACEOAA"
ERIK_ID = "0038c00000ERIKLIAA"
EDUCATION_ID = "0068c00000EDUSAVAA"
ROLLOVER_ID = "0068c00000ROLLOVAA"
CALL_TASK_ID = "00T8c00000CALLGOAA"
RISK_TASK_ID = "00T8c00000RISKPRAA"
REVIEW_EVENT_ID = "00U8c00000REVIEWAA"
CHECKIN_EVENT_ID = "00U8c00000RETCHKAA"
PRIYA_EVENT_ID = "00U8c00000PRIYAEAA"
BENEFICIARY_CASE_ID = "5008c00000BENEFIAA"
PREFIX = {
    "User": "005",
    "Account": "001",
    "Contact": "003",
    "Opportunity": "006",
    "Task": "00T",
    "Event": "00U",
    "Case": "500",
}
# Each object's fields as describe lists them, with their Salesforce types. User has no owner, as in Salesforce.
_SYSTEM = (
    ("Id", "id"),
    ("OwnerId", "reference"),
    ("CreatedDate", "datetime"),
    ("LastModifiedDate", "datetime"),
    ("CreatedById", "reference"),
    ("LastModifiedById", "reference"),
)
FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "User": (
        ("Id", "id"), ("Name", "string"), ("FirstName", "string"), ("LastName", "string"), ("Username", "string"),
        ("Email", "email"), ("Title", "string"), ("IsActive", "boolean"), ("CreatedDate", "datetime"),
        ("LastModifiedDate", "datetime"),
    ),
    "Account": (
        *_SYSTEM, ("Name", "string"), ("Type", "picklist"), ("Phone", "phone"), ("Description", "textarea"),
        ("LastActivityDate", "date"),
    ),
    "Contact": (
        *_SYSTEM, ("Name", "string"), ("FirstName", "string"), ("LastName", "string"), ("Title", "string"),
        ("Email", "email"), ("Phone", "phone"), ("AccountId", "reference"), ("LastActivityDate", "date"),
    ),
    "Opportunity": (
        *_SYSTEM, ("Name", "string"), ("AccountId", "reference"), ("StageName", "picklist"), ("Amount", "currency"),
        ("CloseDate", "date"), ("NextStep", "string"), ("Description", "textarea"), ("IsClosed", "boolean"),
        ("IsWon", "boolean"),
    ),
    "Task": (
        *_SYSTEM, ("Subject", "string"), ("Status", "picklist"), ("Priority", "picklist"), ("ActivityDate", "date"),
        ("Description", "textarea"), ("Type", "picklist"), ("WhatId", "reference"), ("WhoId", "reference"),
        ("IsClosed", "boolean"),
    ),
    "Event": (
        *_SYSTEM, ("Subject", "string"), ("StartDateTime", "datetime"), ("EndDateTime", "datetime"),
        ("ActivityDate", "date"), ("DurationInMinutes", "int"), ("Location", "string"), ("Description", "textarea"),
        ("WhatId", "reference"), ("WhoId", "reference"),
    ),
    "Case": (
        *_SYSTEM, ("CaseNumber", "string"), ("Subject", "string"), ("Status", "picklist"), ("Priority", "picklist"),
        ("Description", "textarea"), ("AccountId", "reference"), ("ContactId", "reference"), ("IsClosed", "boolean"),
    ),
}  # fmt: skip
PICKLISTS: dict[tuple[str, str], tuple[str, ...]] = {
    ("Opportunity", "StageName"): (
        "Prospecting", "Qualification", "Needs Analysis", "Proposal", "Negotiation", "Closed Won", "Closed Lost",
    ),
    ("Task", "Status"): ("Not Started", "In Progress", "Completed"),
    ("Task", "Priority"): ("High", "Normal", "Low"),
    ("Task", "Type"): ("Call", "Email", "Meeting", "Other"),
    ("Account", "Type"): ("Household", "Business", "Prospect"),
    ("Case", "Status"): ("New", "Working", "Escalated", "Closed"),
    ("Case", "Priority"): ("High", "Medium", "Low"),
}  # fmt: skip
# Picklists Salesforce refuses an unlisted value for; the others take any text, as an unrestricted picklist does.
RESTRICTED = {("Opportunity", "StageName"), ("Task", "Status")}
REQUIRED = {
    "Opportunity": ("Name", "StageName", "CloseDate"),
    "Task": ("Subject",),
    "Account": ("Name",),
    "Contact": ("LastName",),
}
# Set by the org, never by a write: the record's identity, its audit stamps and the flags derived from other fields.
READ_ONLY = frozenset(
    {"Id", "CreatedDate", "LastModifiedDate", "CreatedById", "LastModifiedById", "IsClosed", "IsWon", "CaseNumber"}
)
DEFAULTS: dict[str, dict[str, Any]] = {
    "Task": {"Status": "Not Started", "Priority": "Normal"},
    "Case": {"Status": "New", "Priority": "Medium"},
}
REFERENCES = {
    "OwnerId": ["User"],
    "CreatedById": ["User"],
    "LastModifiedById": ["User"],
    "AccountId": ["Account"],
    "ContactId": ["Contact"],
    "WhoId": ["Contact"],
    "WhatId": ["Account", "Opportunity", "Case"],
}
# Who and What point at more than one object; their Type names the one a record points at.
POLYMORPHIC = frozenset({"Who", "What"})
# A parent's child relationships a SELECT subquery names: the child object and the field pointing at the parent.
CHILDREN: dict[str, dict[str, tuple[str, str]]] = {
    "Account": {
        "Contacts": ("Contact", "AccountId"),
        "Opportunities": ("Opportunity", "AccountId"),
        "Cases": ("Case", "AccountId"),
        "Tasks": ("Task", "WhatId"),
        "Events": ("Event", "WhatId"),
    },
    "Contact": {"Tasks": ("Task", "WhoId"), "Events": ("Event", "WhoId"), "Cases": ("Case", "ContactId")},
    "Opportunity": {"Tasks": ("Task", "WhatId"), "Events": ("Event", "WhatId")},
    "Case": {"Tasks": ("Task", "WhatId"), "Events": ("Event", "WhatId")},
}
LABELS = {"StageName": "Stage", "WhoId": "Name ID", "WhatId": "Related To ID"}
Record = dict[str, Any]
# A REST answer: its status and JSON body.
Answer = tuple[int, Any]
# One WHERE condition, given the object queried and one of its records.
Test = Callable[[str, Record], bool]
# The words that end a SOQL clause when they stand outside parentheses.
_CLAUSES = frozenset({"WHERE", "USING", "ORDER", "LIMIT", "OFFSET", "GROUP", "HAVING", "WITH", "FOR"})
_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:\\.|[^'\\])*')"
    r"|(?P<when>\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)"
    r"|(?P<number>-?\d+(?:\.\d+)?)"
    r"|(?P<op>!=|<>|<=|>=|=|<|>)"
    r"|(?P<punct>[(),])"
    r"|(?P<word>[A-Za-z_][\w.]*(?::-?\d+)?)"
    r"|(?P<other>\S))"
)
_SUBREQUEST = re.compile(r"/services/data/v[\d.]+/(?:sobjects/(\w+)(?:/([^/]+))?|query/?)")
_REFERENCE = re.compile(r"@\{([^}]+)\}")
_HALTED = "The transaction was rolled back since another operation in the same transaction failed."


def _sf_time(at: datetime) -> str:
    """A time as Salesforce writes one: in UTC, to the millisecond, with a +0000 offset."""
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000+0000")


def _midnight(day: date) -> datetime:
    """The start of a day on this machine's clock, which is the user's time zone for every date literal."""
    return datetime(day.year, day.month, day.day).astimezone()


def seed_records(now: datetime) -> dict[str, dict[str, Record]]:
    """Dana Whitfield's org on the day the fake starts: two clients, their contacts, the education-savings
    opportunity, the call that raised it, today's annual review and check-in, and one meeting of another advisor's.
    `now` is local and aware, so today's 14:00 review is 14:00 wherever the fake runs."""
    today = now.date()

    def at(days: int, hour: int = 9, minute: int = 0) -> str:
        day = today + timedelta(days=days)
        return _sf_time(datetime(day.year, day.month, day.day, hour, minute).astimezone())

    def on(days: int) -> str:
        return (today + timedelta(days=days)).isoformat()

    def stamped(owner: str, created: str, changed: str) -> Record:
        return {
            "OwnerId": owner,
            "CreatedDate": created,
            "LastModifiedDate": changed,
            "CreatedById": owner,
            "LastModifiedById": owner,
        }

    last_year = date(today.year - 1, 9, 18)
    users = [
        {"Id": DANA_ID, "Name": "Dana Whitfield", "FirstName": "Dana", "LastName": "Whitfield",
         "Username": DANA_USERNAME, "Email": "dana.whitfield@harborpine.example", "Title": "Financial Advisor",
         "IsActive": True, "CreatedDate": "2018-09-04T13:00:00.000+0000", "LastModifiedDate": at(-30)},
        {"Id": PRIYA_ID, "Name": "Priya Raman", "FirstName": "Priya", "LastName": "Raman", "Username": "priya.raman",
         "Email": "priya.raman@harborpine.example", "Title": "Financial Advisor", "IsActive": True,
         "CreatedDate": "2020-02-10T13:00:00.000+0000", "LastModifiedDate": at(-30)},
    ]  # fmt: skip
    accounts = [
        {"Id": OKAFOR_ID, "Name": "Okafor Family Trust", "Type": "Household", "Phone": "(555) 014-2290",
         "Description": "Household client since 2019. Annual review due this month; risk profile last refreshed "
         "14 months ago.", "LastActivityDate": on(-17),
         **stamped(DANA_ID, "2019-04-02T14:00:00.000+0000", at(-17, 11, 30))},
        {"Id": LINDQVIST_ID, "Name": "Lindqvist Dental Group", "Type": "Business", "Phone": "(555) 017-8834",
         "Description": "Dental practice with three clinics; the partners' retirement plan is held here.",
         "LastActivityDate": on(-40), **stamped(DANA_ID, "2021-06-15T15:00:00.000+0000", at(-40))},
    ]  # fmt: skip
    contacts = [
        {"Id": GRACE_ID, "Name": "Grace Okafor", "FirstName": "Grace", "LastName": "Okafor", "Title": "Trustee",
         "Email": "grace.okafor@example.com", "Phone": "(555) 014-2291", "AccountId": OKAFOR_ID,
         "LastActivityDate": on(-17), **stamped(DANA_ID, "2019-04-02T14:05:00.000+0000", at(-17, 11, 30))},
        {"Id": ERIK_ID, "Name": "Erik Lindqvist", "FirstName": "Erik", "LastName": "Lindqvist",
         "Title": "Managing partner", "Email": "erik.lindqvist@example.com", "Phone": "(555) 017-8835",
         "AccountId": LINDQVIST_ID, "LastActivityDate": on(-40),
         **stamped(DANA_ID, "2021-06-15T15:05:00.000+0000", at(-40))},
    ]  # fmt: skip
    opportunities = [
        {"Id": EDUCATION_ID, "Name": "Education savings", "AccountId": OKAFOR_ID, "StageName": "Needs Analysis",
         "Amount": 50000, "CloseDate": on(60), "NextStep": "Propose a plan for two children's education",
         "Description": None, "IsClosed": False, "IsWon": False, **stamped(DANA_ID, at(-24), at(-21))},
        {"Id": ROLLOVER_ID, "Name": "Retirement account rollover", "AccountId": OKAFOR_ID,
         "StageName": "Closed Won", "Amount": 180000, "CloseDate": last_year.isoformat(), "NextStep": None,
         "Description": None, "IsClosed": True, "IsWon": True,
         **stamped(DANA_ID, _sf_time(_midnight(last_year - timedelta(days=45))), _sf_time(_midnight(last_year)))},
    ]  # fmt: skip
    tasks = [
        {"Id": CALL_TASK_ID, "Subject": "Call with Grace Okafor", "Status": "Completed", "Priority": "Normal",
         "ActivityDate": on(-17), "Description": "Asked about saving for two children's education. Cash is 18% of "
         "the portfolio against a 5% target.", "Type": "Call", "WhatId": OKAFOR_ID, "WhoId": GRACE_ID,
         "IsClosed": True, **stamped(DANA_ID, at(-17, 11), at(-17, 11, 30))},
        {"Id": RISK_TASK_ID, "Subject": "Refresh risk profile", "Status": "Not Started", "Priority": "High",
         "ActivityDate": on(0), "Description": "Last refreshed 14 months ago; due before the annual review.",
         "Type": "Other", "WhatId": OKAFOR_ID, "WhoId": None, "IsClosed": False,
         **stamped(DANA_ID, at(-3), at(-3))},
    ]  # fmt: skip
    events = [
        {"Id": REVIEW_EVENT_ID, "Subject": "Annual review: Okafor Family Trust", "StartDateTime": at(0, 14),
         "EndDateTime": at(0, 15), "ActivityDate": on(0), "DurationInMinutes": 60, "Location": "Office",
         "Description": None, "WhatId": OKAFOR_ID, "WhoId": GRACE_ID, **stamped(DANA_ID, at(-10), at(-10))},
        {"Id": CHECKIN_EVENT_ID, "Subject": "Retirement plan check-in", "StartDateTime": at(0, 16, 30),
         "EndDateTime": at(0, 17, 30), "ActivityDate": on(0), "DurationInMinutes": 60, "Location": "Video call",
         "Description": None, "WhatId": LINDQVIST_ID, "WhoId": ERIK_ID, **stamped(DANA_ID, at(-8), at(-8))},
        {"Id": PRIYA_EVENT_ID, "Subject": "Portfolio review: Chen household", "StartDateTime": at(0, 11),
         "EndDateTime": at(0, 12), "ActivityDate": on(0), "DurationInMinutes": 60, "Location": "Branch",
         "Description": None, "WhatId": None, "WhoId": None, **stamped(PRIYA_ID, at(-6), at(-6))},
    ]  # fmt: skip
    cases = [
        {"Id": BENEFICIARY_CASE_ID, "CaseNumber": "00045120", "Subject": "Update the beneficiary on the trust account",
         "Status": "Working", "Priority": "Medium", "Description": "Grace Okafor asked to name a contingent "
         "beneficiary on the trust account.", "AccountId": OKAFOR_ID, "ContactId": GRACE_ID, "IsClosed": False,
         **stamped(DANA_ID, at(-12), at(-5))},
    ]  # fmt: skip
    rows = {
        "User": users,
        "Account": accounts,
        "Contact": contacts,
        "Opportunity": opportunities,
        "Task": tasks,
        "Event": events,
        "Case": cases,
    }
    return {obj: {str(r["Id"]): r for r in found} for obj, found in rows.items()}


@dataclass(frozen=True)
class _Span:
    """A date literal's days, from `start` up to but not including `end`."""

    start: date
    end: date


def date_span(literal: str, today: date) -> _Span | None:
    """The days a SOQL date literal names, or None for a literal this fake does not know. Weeks start on Sunday, as
    in Salesforce's en_US locale; LAST_N_DAYS:n is today and the n days before it, and NEXT_N_DAYS:n the n days after
    today, as Salesforce's SOQL reference defines them."""
    name, _, count = literal.upper().partition(":")
    day = timedelta(days=1)
    if count:
        if not count.lstrip("-").isdigit():
            return None
        n = int(count)
        if name == "LAST_N_DAYS":
            return _Span(today - n * day, today + day)
        if name == "NEXT_N_DAYS":
            return _Span(today + day, today + (n + 1) * day)
        return _Span(today - n * day, today - (n - 1) * day) if name == "N_DAYS_AGO" else None
    week = today - timedelta(days=(today.weekday() + 1) % 7)
    month = today.replace(day=1)
    next_month = (month + 32 * day).replace(day=1)
    year = date(today.year, 1, 1)
    fixed = {
        "TODAY": _Span(today, today + day),
        "YESTERDAY": _Span(today - day, today),
        "TOMORROW": _Span(today + day, today + 2 * day),
        "THIS_WEEK": _Span(week, week + 7 * day),
        "LAST_WEEK": _Span(week - 7 * day, week),
        "NEXT_WEEK": _Span(week + 7 * day, week + 14 * day),
        "THIS_MONTH": _Span(month, next_month),
        "LAST_MONTH": _Span((month - day).replace(day=1), month),
        "NEXT_MONTH": _Span(next_month, (next_month + 32 * day).replace(day=1)),
        "THIS_YEAR": _Span(year, date(today.year + 1, 1, 1)),
        "LAST_YEAR": _Span(date(today.year - 1, 1, 1), year),
    }
    return fixed.get(name)


def _instant(value: Any) -> datetime | None:
    """A stored date or datetime as an aware time: a date is its local midnight."""
    if not isinstance(value, str):
        return None
    if len(value) == 10:
        try:
            return _midnight(date.fromisoformat(value))
        except ValueError:
            return None
    return _when(value)


def _order(have: Any, op: str, want: Any) -> bool:
    try:
        return {
            "=": have == want,
            "!=": have != want,
            "<": have < want,
            "<=": have <= want,
            ">": have > want,
            ">=": have >= want,
        }[op]
    except TypeError:
        return False


def _same_text(have: str, want: str) -> bool:
    """Text equality as SOQL has it: case-insensitive, and an id's 15-character form equal to its 18-character one."""
    if {len(have), len(want)} == {15, 18}:
        return have[:15] == want[:15]
    return have.lower() == want.lower()


def _matches(have: Any, op: str, want: Any) -> bool:
    """One SOQL comparison of a record's value with a literal. A null field is unequal to every value, so `!=`
    keeps it; a datetime field compared with a date literal compares by the local days the literal names."""
    if want is None or have is None:
        both = have is None and want is None
        return both if op == "=" else (not both) if op == "!=" else False
    if isinstance(want, _Span):
        at = _instant(have)
        if at is None:
            return False
        start, end = _midnight(want.start), _midnight(want.end)
        inside = start <= at < end
        return {"=": inside, "!=": not inside, "<": at < start, "<=": at < end, ">": at >= end, ">=": at >= start}[op]
    if isinstance(want, datetime):
        at = _instant(have)
        return at is not None and _order(at, op, want)
    if isinstance(want, date):
        if isinstance(have, str) and len(have) == 10:
            return _order(have, op, want.isoformat())
        return _matches(have, op, _Span(want, want + timedelta(days=1)))
    if isinstance(want, bool):
        return (have is want) == (op == "=") if op in ("=", "!=") else False
    if isinstance(want, int | float):
        if isinstance(have, bool) or not isinstance(have, int | float | str):
            return False
        try:
            return _order(float(have), op, float(want))
        except ValueError:
            return False
    if isinstance(want, str) and isinstance(have, str):
        if op in ("=", "!="):
            return _same_text(have, want) == (op == "=")
        return _order(have.lower(), op, want.lower())
    return op == "!="


def _unquote(token: str) -> str:
    escapes = {"n": "\n", "t": "\t", "r": "\r"}
    return re.sub(r"\\(.)", lambda m: escapes.get(m[1], m[1]), token[1:-1])


def _like(pattern: str) -> re.Pattern[str]:
    """A LIKE pattern as a case-insensitive regular expression: % is any run of characters and _ any one."""
    body = "".join(".*" if c == "%" else "." if c == "_" else re.escape(c) for c in pattern)
    return re.compile(body, re.IGNORECASE | re.DOTALL)


def _sort_key(value: Any) -> Any:
    if isinstance(value, str):
        return value.lower()
    return int(value) if isinstance(value, bool) else value


def _always(obj: str, record: Record) -> bool:
    return True


def _object(value: Any) -> dict[str, Any] | None:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else None


def _parsed(body: bytes) -> Any:
    try:
        return json.loads(body or b"{}")
    except ValueError:
        return None


@dataclass
class _Count:
    """COUNT() or COUNT(field) in a SELECT list, under its alias."""

    field: str | None
    alias: str | None


@dataclass
class _Child:
    """A child relationship's subquery in a SELECT list, such as (SELECT Subject FROM Tasks)."""

    query: Soql


@dataclass
class Soql:
    """One parsed query. `items` holds field paths, "*" for FIELDS(...), counts and child subqueries; `notes` holds
    the parts the parser could not read, each skipped."""

    obj: str
    items: list[str | _Count | _Child]
    scope: str | None = None
    where: Test = _always
    order: list[tuple[str, bool, bool]] = default(default_factory=list[tuple[str, bool, bool]])
    limit: int | None = None
    offset: int = 0
    notes: list[str] = default(default_factory=list[str])


class _Unparsed(Exception):
    """A condition the parser cannot read; it is skipped and noted."""


class _Parser:
    """Recursive descent over SOQL tokens between `start` and `end`. A condition it cannot read is noted and treated
    as true, because the model writes free SOQL and a refusal from a fake would test the fake, not the model."""

    def __init__(
        self, org: Org, tokens: list[tuple[str, str]], notes: list[str], start: int = 0, end: int = -1
    ) -> None:
        self.org, self.t, self.notes = org, tokens, notes
        self.i, self.end = start, len(tokens) if end < 0 else end

    def peek(self, ahead: int = 0) -> tuple[str, str]:
        at = self.i + ahead
        return self.t[at] if at < self.end else ("end", "")

    def take(self) -> tuple[str, str]:
        token = self.peek()
        self.i += 1
        return token

    def word(self, *names: str) -> bool:
        kind, text = self.peek()
        return kind == "word" and text.upper() in names

    def text(self, start: int, end: int) -> str:
        return " ".join(t for _, t in self.t[start:end])

    def closing(self, at: int) -> int:
        """The index of the parenthesis closing the one at `at`, or the end when it is never closed."""
        depth = 0
        for k in range(at, self.end):
            depth += {"(": 1, ")": -1}.get(self.t[k][1], 0) if self.t[k][0] == "punct" else 0
            if depth == 0:
                return k
        return self.end

    def clause_end(self) -> int:
        depth, k = 0, self.i
        while k < self.end:
            kind, text = self.t[k]
            depth += {"(": 1, ")": -1}.get(text, 0) if kind == "punct" else 0
            if depth == 0 and kind == "word" and text.upper() in _CLAUSES:
                break
            k += 1
        return k

    def note(self, start: int, end: int) -> None:
        if end > start:
            self.notes.append(self.text(start, end))

    def query(self) -> Soql | None:
        """A whole query, or None when it has no SELECT ... FROM <object> to answer."""
        if not self.word("SELECT"):
            return None
        self.take()
        items: list[str | _Count | _Child] = []
        while self.i < self.end and not self.word("FROM"):
            start = self.i
            item = self.select_item()
            if item is None:
                self.note(start, self.i)
            else:
                items.append(item)
            if self.peek() == ("punct", ","):
                self.take()
        if not self.word("FROM"):
            return None
        self.take()
        kind, name = self.take()
        if kind != "word":
            return None
        soql = Soql(obj=name, items=items, notes=self.notes)
        while self.i < self.end:
            start = self.i
            if self.word("USING") and self.peek(1)[1].upper() == "SCOPE":
                self.i += 2
                soql.scope = self.take()[1].lower()
            elif self.word("WHERE"):
                self.take()
                stop = self.clause_end()
                soql.where = _Parser(self.org, self.t, self.notes, self.i, stop).conditions()
                self.i = stop
            elif self.word("ORDER") and self.peek(1)[1].upper() == "BY":
                self.i += 2
                soql.order = self.order_by()
            elif self.word("LIMIT", "OFFSET"):
                clause = self.take()[1].upper()
                kind, text = self.take()
                if kind != "number":
                    self.note(start, self.i)
                elif clause == "LIMIT":
                    soql.limit = int(float(text))
                else:
                    soql.offset = int(float(text))
            else:
                self.take()
                self.i = self.clause_end()
                self.note(start, self.i)
        return soql

    def select_item(self) -> str | _Count | _Child | None:
        kind, text = self.peek()
        if (kind, text) == ("punct", "("):
            close = self.closing(self.i)
            sub = _Parser(self.org, self.t, self.notes, self.i + 1, close).query()
            self.i = close + 1
            return _Child(sub) if sub else None
        if kind == "word" and self.peek(1) == ("punct", "("):
            close = self.closing(self.i + 1)
            inner = self.text(self.i + 2, close)
            self.i = close + 1
            alias = self.take()[1] if self.peek()[0] == "word" and not self.word("FROM") else None
            if text.upper() == "COUNT":
                return _Count(inner or None, alias)
            return "*" if text.upper() == "FIELDS" else None
        self.take()
        return text if kind == "word" else None

    def order_by(self) -> list[tuple[str, bool, bool]]:
        """ORDER BY's fields: each its path, whether descending, and whether nulls come first (by default first
        ascending and last descending, as in Salesforce)."""
        out: list[tuple[str, bool, bool]] = []
        while self.i < self.end and not self.word(*_CLAUSES):
            kind, path = self.take()
            if kind != "word":
                continue
            descending = self.word("DESC")
            if self.word("ASC", "DESC"):
                self.take()
            nulls_first = not descending
            if self.word("NULLS"):
                self.take()
                nulls_first = self.take()[1].upper() == "FIRST"
            out.append((path, descending, nulls_first))
        return out

    def conditions(self) -> Test:
        test = self.any_of()
        self.note(self.i, self.end)
        return test

    def any_of(self) -> Test:
        parts = [self.all_of()]
        while self.word("OR"):
            self.take()
            parts.append(self.all_of())
        return parts[0] if len(parts) == 1 else lambda obj, r: any(p(obj, r) for p in parts)

    def all_of(self) -> Test:
        parts = [self.negated()]
        while self.word("AND"):
            self.take()
            parts.append(self.negated())
        return parts[0] if len(parts) == 1 else lambda obj, r: all(p(obj, r) for p in parts)

    def negated(self) -> Test:
        if self.word("NOT"):
            self.take()
            inner = self.negated()
            return lambda obj, r: not inner(obj, r)
        return self.primary()

    def primary(self) -> Test:
        start = self.i
        if self.peek() == ("punct", "("):
            self.take()
            inner = self.any_of()
            if self.peek() == ("punct", ")"):
                self.take()
            return inner
        try:
            return self.comparison()
        except _Unparsed:
            self.i, depth = start, 0
            while self.i < self.end:
                kind, text = self.peek()
                if kind == "punct" and text in "()":
                    if text == ")" and depth == 0:
                        break
                    depth += 1 if text == "(" else -1
                elif depth == 0 and kind == "word" and text.upper() in ("AND", "OR"):
                    break
                self.take()
            self.note(start, self.i)
            return _always

    def comparison(self) -> Test:
        kind, path = self.take()
        if kind != "word" or path.upper() in ("AND", "OR", "NOT"):
            raise _Unparsed
        negate = self.word("NOT")
        if negate:
            self.take()
        kind, op = self.take()
        org = self.org
        if kind == "op" and not negate:
            want = self.literal()
            op = "!=" if op == "<>" else op
            return lambda obj, r: _matches(org.value(obj, r, path), op, want)
        if kind == "word" and op.upper() == "LIKE":
            kind, text = self.take()
            if kind != "string":
                raise _Unparsed
            pattern = _like(_unquote(text))

            def like(obj: str, r: Record) -> bool:
                have = org.value(obj, r, path)
                return (isinstance(have, str) and pattern.fullmatch(have) is not None) != negate

            return like
        if kind == "word" and op.upper() == "IN" and self.peek() == ("punct", "("):
            return self.membership(path, negate)
        raise _Unparsed

    def membership(self, path: str, negate: bool) -> Test:
        """IN or NOT IN a list of literals, or a semi-join's subquery, whose first field's values are the list."""
        close = self.closing(self.i)
        org = self.org
        if self.peek(1)[1].upper() == "SELECT":
            sub = _Parser(org, self.t, self.notes, self.i + 1, close).query()
            if sub is None or not sub.items or not isinstance(sub.items[0], str):
                raise _Unparsed
            self.i = close + 1
            column = sub.items[0]
            known: list[list[Any]] = []

            def values() -> list[Any]:
                if not known:
                    rows = org.run(sub, "")
                    known.append([org.value(org.object_name(sub.obj) or sub.obj, row, column) for row in rows])
                return known[0]

            return lambda obj, r: any(_matches(org.value(obj, r, path), "=", v) for v in values()) != negate
        inner = _Parser(org, self.t, self.notes, self.i + 1, close)
        found: list[Any] = []
        while inner.i < inner.end:
            if inner.peek() == ("punct", ","):
                inner.take()
                continue
            found.append(inner.literal())
        self.i = close + 1
        return lambda obj, r: any(_matches(org.value(obj, r, path), "=", v) for v in found) != negate

    def literal(self) -> Any:
        kind, text = self.take()
        if kind == "string":
            return _unquote(text)
        if kind == "number":
            return float(text) if "." in text else int(text)
        if kind == "when":
            if len(text) == 10:
                try:
                    return date.fromisoformat(text)
                except ValueError as e:
                    raise _Unparsed from e
            at = _when(text)
            if at is None:
                raise _Unparsed
            return at
        if kind == "word":
            upper = text.upper()
            if upper in ("TRUE", "FALSE", "NULL"):
                return {"TRUE": True, "FALSE": False, "NULL": None}[upper]
            span = date_span(upper, datetime.now().astimezone().date())
            if span is not None:
                return span
        raise _Unparsed


class Org:
    """The advisor org: records by object and id, and Salesforce's answers over them: SOQL, record reads and writes,
    describe, composite and SOSL. Writes append to `edits` with the signer, refusals of scope to `refused`, every
    query to `queries`, and conditions the evaluator could not read to `unparsed`."""

    def __init__(
        self, edits: list[dict[str, Any]], refused: list[str], queries: list[str], now: datetime | None = None
    ) -> None:
        self.records = seed_records((now or datetime.now()).astimezone())
        self.edits, self.refused, self.queries = edits, refused, queries
        self.unparsed: list[str] = []
        self._made = 0

    # Reading records.

    def object_name(self, name: str) -> str | None:
        return next((o for o in FIELDS if o.lower() == name.lower()), None)

    def field(self, obj: str, name: str) -> str:
        """A field's name as the object spells it; SOQL and REST bodies name fields in any case."""
        return next((f for f, _ in FIELDS.get(obj, ()) if f.lower() == name.lower()), name)

    def find(self, rid: str) -> tuple[str, Record] | None:
        for obj, rows in self.records.items():
            if rid in rows:
                return obj, rows[rid]
            if len(rid) == 15:
                for key, row in rows.items():
                    if key[:15] == rid:
                        return obj, row
        return None

    def user_named(self, who: str) -> Record | None:
        """The User a token's subject signs in as, by username or email."""
        users = self.records["User"].values()
        return next((u for u in users if who.lower() in (str(u["Username"]).lower(), str(u["Email"]).lower())), None)

    def user(self, who: str) -> Record:
        """The signed-in User; a subject the org does not hold is its first user, Dana Whitfield."""
        return self.user_named(who) or next(iter(self.records["User"].values()))

    def relation(self, obj: str, record: Record, name: str) -> tuple[str | None, tuple[str, Record] | None]:
        """A relationship's name as the object spells it and the record it points at; (None, None) when the object
        has no such relationship, and (name, None) when the pointer is empty."""
        for f, kind in FIELDS.get(obj, ()):
            if kind == "reference" and f[:-2].lower() == name.lower():
                pointer = record.get(f)
                return f[:-2], self.find(pointer) if isinstance(pointer, str) else None
        return None, None

    def value(self, obj: str, record: Record, path: str) -> Any:
        head, _, rest = path.partition(".")
        if not rest:
            return record.get(self.field(obj, head))
        rel, target = self.relation(obj, record, head)
        if target is None:
            return None
        if rel in POLYMORPHIC and rest.lower() == "type":
            return target[0]
        return self.value(target[0], target[1], rest)

    def attributes(self, obj: str, record: Record) -> dict[str, str]:
        return {"type": obj, "url": f"{API}/sobjects/{obj}/{record['Id']}"}

    def put(self, out: dict[str, Any], obj: str, record: Record, path: str) -> None:
        """One SELECT path into an answer record: a relationship's fields nest under its name, as Salesforce's do."""
        head, _, rest = path.partition(".")
        if not rest:
            name = self.field(obj, head)
            out[name] = record.get(name)
            return
        rel, target = self.relation(obj, record, head)
        if rel is None:
            self.unparsed.append(f"no relationship {obj}.{head}")
            return
        if target is None:
            out.setdefault(rel, None)
            return
        nested = _object(out.get(rel)) or {"attributes": self.attributes(*target)}
        if rel in POLYMORPHIC and rest.lower() == "type":
            nested["Type"] = target[0]
        else:
            self.put(nested, target[0], target[1], rest)
        out[rel] = nested

    # SOQL.

    def parse(self, q: str) -> Soql | None:
        tokens = [(m.lastgroup or "other", m[m.lastgroup or 0]) for m in _TOKEN.finditer(q) if m.lastgroup]
        return _Parser(self, tokens, []).query()

    def answers(self, q: str) -> bool:
        """Whether a query is the org's to answer: one on its own objects, or on Case when it concerns the org's
        accounts or cases or reads IsClosed. Every other Case query keeps the case handlers' answer."""
        soql = self.parse(q)
        obj = self.object_name(soql.obj) if soql else None
        if obj is None:
            return False
        if obj != "Case":
            return True
        marks = [m for a in self.records["Account"].values() for m in (str(a["Id"]), str(a["Id"])[:15], a["Name"])]
        marks += [m for c in self.records["Case"].values() for m in (str(c["Id"])[:15], c["CaseNumber"])]
        return bool(re.search(r"\bIsClosed\b|\bAccount\.", q, re.IGNORECASE)) or any(m and m in q for m in marks)

    def run(self, soql: Soql, me: str, among: list[Record] | None = None, obj: str | None = None) -> list[Record]:
        """The records a query selects, in its order, after its OFFSET and LIMIT. USING SCOPE mine keeps the
        records `me` owns; a User is its own."""
        obj = obj or self.object_name(soql.obj) or soql.obj
        rows = list(self.records.get(obj, {}).values()) if among is None else among
        if soql.scope == "mine":
            rows = [r for r in rows if r.get("OwnerId", r["Id"]) == me]
        elif soql.scope not in (None, "everything"):
            self.unparsed.append(f"USING SCOPE {soql.scope}")
        rows = [r for r in rows if soql.where(obj, r)]
        for path, descending, nulls_first in reversed(soql.order):
            # Python's sort is stable, so sorting by the last key first leaves the first key deciding.
            null_rank = 0 if nulls_first != descending else 2

            def key(r: Record, path: str = path, null_rank: int = null_rank) -> tuple[int, Any]:
                have = self.value(obj, r, path)
                return (null_rank, 0) if have is None else (1, _sort_key(have))

            rows.sort(key=key, reverse=descending)
        rows = rows[soql.offset :]
        return rows if soql.limit is None else rows[: soql.limit]

    def shape(self, obj: str, record: Record, soql: Soql, me: str) -> Record:
        out: Record = {"attributes": self.attributes(obj, record)}
        for item in soql.items:
            if item == "*":
                out |= {f: record.get(f) for f, _ in FIELDS.get(obj, ())} | {
                    k: v for k, v in record.items() if k not in out
                }
            elif isinstance(item, _Child):
                child = next((v for k, v in CHILDREN.get(obj, {}).items() if k.lower() == item.query.obj.lower()), None)
                if child is None:
                    self.unparsed.append(f"no child relationship {obj}.{item.query.obj}")
                    continue
                name = next(k for k in CHILDREN[obj] if k.lower() == item.query.obj.lower())
                mine = [c for c in self.records.get(child[0], {}).values() if c.get(child[1]) == record["Id"]]
                rows = self.run(item.query, me, mine, child[0])
                out[name] = (
                    {
                        "totalSize": len(rows),
                        "done": True,
                        "records": [self.shape(child[0], c, item.query, me) for c in rows],
                    }
                    if rows
                    else None
                )
            elif isinstance(item, str):
                self.put(out, obj, record, item)
        return out

    def query(self, q: str, who: str) -> dict[str, Any]:
        """A SOQL query's answer in Salesforce's shape; the caller has checked the org `answers` it."""
        self.queries.append(q)
        soql = self.parse(q)
        if soql is None:
            return {"totalSize": 0, "done": True, "records": []}
        obj = self.object_name(soql.obj) or soql.obj
        me = str(self.user(who)["Id"])
        rows = self.run(soql, me)
        self.unparsed.extend(soql.notes)
        counts = [i for i in soql.items if isinstance(i, _Count)]
        if counts and counts[0].field is None:
            return {"totalSize": len(rows), "done": True, "records": []}
        if counts:
            totals = {c.alias or f"expr{n}": len(rows) for n, c in enumerate(counts)}
            return {"totalSize": 1, "done": True, "records": [{"attributes": {"type": "AggregateResult"}, **totals}]}
        return {"totalSize": len(rows), "done": True, "records": [self.shape(obj, r, soql, me) for r in rows]}

    # REST records.

    def owns_case(self, parts: list[str], body: Any) -> bool:
        """Whether a Case record call is the org's: a read or write of its own case, or a case created on one of
        its accounts. Any other stays with the case handlers."""
        if len(parts) == 2:
            found = self.find(parts[1])
            return found is not None and found[0] == "Case"
        fields = _object(body) or {}
        account = next((v for k, v in fields.items() if k.lower() == "accountid"), None)
        return len(parts) == 1 and isinstance(account, str) and self.find(account) is not None

    def get(self, obj: str, rid: str, fields: list[str] | None = None) -> Answer:
        found = self.find(rid)
        if found is None or found[0] != obj:
            return 404, [{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}]
        record = found[1]
        names = [self.field(obj, f.strip()) for f in fields] if fields else list(record)
        return 200, {"attributes": self.attributes(obj, record), **{n: record.get(n) for n in names}}

    def _refuse(self, who: str, scopes: set[str]) -> Answer | None:
        """Writes to the org's records need the `api` scope, as in Salesforce, where the user's own permissions then
        decide; a token signed in without it is refused."""
        if ORG_WRITE_SCOPE in scopes:
            return None
        self.refused.append(f"insufficient_scope:{who}")
        return 403, [{"errorCode": "INSUFFICIENT_ACCESS", "message": f"needs {ORG_WRITE_SCOPE}"}]

    def _check(self, obj: str, body: dict[str, Any], creating: bool) -> tuple[Record, list[dict[str, Any]]]:
        """A write's fields under the object's spelling, dates normalised, with Salesforce's errors for a value of the
        wrong type, a missing required field and a value outside a restricted picklist."""
        kinds = dict(FIELDS.get(obj, ()))
        clean: Record = {}
        errors: list[dict[str, Any]] = []
        for key, given in body.items():
            name = self.field(obj, key)
            kind = kinds.get(name)
            if given is None or kind not in ("date", "datetime"):
                clean[name] = given
                continue
            at = _when(str(given))
            if at is None or (kind == "date" and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(T.*)?", str(given))):
                message = f"Cannot deserialize instance of {kind} from VALUE_STRING value {given}"
                errors.append({"errorCode": "JSON_PARSER_ERROR", "message": message, "fields": [name]})
                continue
            clean[name] = str(given)[:10] if kind == "date" else _sf_time(at)
        missing = [
            f
            for f in REQUIRED.get(obj, ())
            if (f in clean or creating) and (clean.get(f) is None or str(clean.get(f)).strip() == "")
        ]
        if missing:
            message = f"Required fields are missing: [{', '.join(missing)}]"
            errors.append({"errorCode": "REQUIRED_FIELD_MISSING", "message": message, "fields": missing})
        for o, f in sorted(RESTRICTED):
            if o == obj and f in clean and f not in missing and clean[f] not in PICKLISTS[(o, f)]:
                message = f"{_label(f)}: bad value for restricted picklist field: {clean[f]}"
                errors.append(
                    {"errorCode": "INVALID_OR_NULL_FOR_RESTRICTED_PICKLIST", "message": message, "fields": [f]}
                )
        return clean, errors

    def _derive(self, obj: str, record: Record) -> None:
        """The fields Salesforce computes from others: a person's full name, and whether a record is closed or won."""
        if obj in ("Contact", "User") and ("FirstName" in record or "LastName" in record):
            record["Name"] = " ".join(str(record[f]) for f in ("FirstName", "LastName") if record.get(f))
        if obj == "Opportunity":
            record["IsClosed"] = record.get("StageName") in ("Closed Won", "Closed Lost")
            record["IsWon"] = record.get("StageName") == "Closed Won"
        if obj in ("Task", "Case"):
            record["IsClosed"] = record.get("Status") in ("Completed", "Closed")
        if obj == "Event" and (start := _when(str(record.get("StartDateTime") or ""))) is not None:
            record["ActivityDate"] = start.astimezone().date().isoformat()

    def create(self, obj: str, body: Any, who: str, scopes: set[str]) -> Answer:
        refused = self._refuse(who, scopes)
        if refused is not None:
            return refused
        fields = _object(body)
        if fields is None:
            return 400, [{"errorCode": "JSON_PARSER_ERROR", "message": "The request body is not a JSON object"}]
        clean, errors = self._check(obj, fields, creating=True)
        if errors:
            return 400, errors
        user, stamp = str(self.user(who)["Id"]), _sf_time(datetime.now(UTC))
        self._made += 1
        rid = f"{PREFIX[obj]}8c00000NEW{self._made:03d}AA"
        record: Record = {"Id": rid, **DEFAULTS.get(obj, {}), **{k: v for k, v in clean.items() if k not in READ_ONLY}}
        record |= {
            "OwnerId": clean.get("OwnerId") or user,
            "CreatedDate": stamp,
            "LastModifiedDate": stamp,
            "CreatedById": user,
            "LastModifiedById": user,
        }
        if obj == "Case":
            record["CaseNumber"] = f"{45120 + self._made:08d}"
        self._derive(obj, record)
        self.records.setdefault(obj, {})[rid] = record
        self.edits.append({"by": who, "object": obj, "op": "create", "change": dict(fields), "id": rid})
        return 201, {"id": rid, "success": True, "errors": []}

    def update(self, obj: str, rid: str, body: Any, who: str, scopes: set[str]) -> Answer:
        refused = self._refuse(who, scopes)
        if refused is not None:
            return refused
        found = self.find(rid)
        if found is None or found[0] != obj:
            return 404, [{"errorCode": "NOT_FOUND", "message": "The requested resource does not exist"}]
        fields = _object(body)
        if fields is None:
            return 400, [{"errorCode": "JSON_PARSER_ERROR", "message": "The request body is not a JSON object"}]
        clean, errors = self._check(obj, fields, creating=False)
        if errors:
            return 400, errors
        record = found[1]
        record |= {k: v for k, v in clean.items() if k not in READ_ONLY}
        record |= {"LastModifiedDate": _sf_time(datetime.now(UTC)), "LastModifiedById": str(self.user(who)["Id"])}
        self._derive(obj, record)
        self.edits.append({"by": who, "object": obj, "op": "update", "change": dict(fields), "id": record["Id"]})
        return 204, None

    def describe(self, obj: str) -> dict[str, Any]:
        fields: list[dict[str, Any]] = []
        for name, kind in FIELDS[obj]:
            fixed = name in READ_ONLY or (obj in ("Contact", "User") and name == "Name")
            fields.append(
                {
                    "name": name,
                    "label": _label(name),
                    "type": kind,
                    "picklistValues": [
                        {"value": v, "label": v, "active": True} for v in PICKLISTS.get((obj, name), ())
                    ],
                    "restrictedPicklist": (obj, name) in RESTRICTED,
                    "nillable": not (fixed or kind == "boolean" or name in REQUIRED.get(obj, ()) or name == "OwnerId"),
                    "createable": not fixed,
                    "updateable": not fixed,
                    "referenceTo": REFERENCES.get(name, []),
                    "relationshipName": name[:-2] if kind == "reference" else None,
                }
            )
        return {"name": obj, "label": obj, "fields": fields}

    # Composite.

    def composite(self, body: Any, who: str, scopes: set[str]) -> dict[str, Any]:
        """Salesforce's composite resource: subrequests applied in order, each able to name an earlier one's answer
        as @{referenceId.field}. With allOrNone, one failure rolls every write back: the failing subrequest carries
        its own error and every other one PROCESSING_HALTED."""
        request = _object(body) or {}
        subs = [s for s in cast("list[Any]", request.get("compositeRequest") or []) if _object(s) is not None]
        all_or_none = bool(request.get("allOrNone"))
        saved, written = copy.deepcopy(self.records), len(self.edits)
        done: dict[str, Any] = {}
        answers: list[dict[str, Any]] = []
        failed = False
        for sub in subs:
            ref = str(sub.get("referenceId", ""))
            if failed:
                answers.append(_halted(ref))
                continue
            status, out = self._subrequest(sub, done, who, scopes)
            answers.append({"body": out, "httpHeaders": {}, "httpStatusCode": status, "referenceId": ref})
            if status < 300:
                done[ref] = out
            elif all_or_none:
                failed = True
        if failed:
            self.records.clear()
            self.records.update(saved)
            del self.edits[written:]
            answers = [a if a["httpStatusCode"] >= 300 else _halted(a["referenceId"]) for a in answers]
        return {"compositeResponse": answers}

    def _subrequest(self, sub: dict[str, Any], done: dict[str, Any], who: str, scopes: set[str]) -> Answer:
        try:
            url = str(_resolved(str(sub.get("url", "")), done))
            body = _resolved(sub.get("body"), done)
        except LookupError as e:
            message = f"Invalid reference specified. No value for {e.args[0]} found."
            return 400, [{"errorCode": "PROCESSING_HALTED", "message": message}]
        method = str(sub.get("method", "GET")).upper()
        parts = urlsplit(url)
        matched = _SUBREQUEST.fullmatch(parts.path)
        if matched is None:
            return 404, [{"errorCode": "NOT_FOUND", "message": url}]
        name, rid = matched[1], matched[2]
        if name is None:
            q = parse_qs(parts.query).get("q", [""])[0]
            if method == "GET" and self.parse(q) is not None:
                return 200, self.query(q, who)
            return 400, [{"errorCode": "MALFORMED_QUERY", "message": q}]
        obj = self.object_name(name)
        if obj is None:
            return 404, [{"errorCode": "NOT_FOUND", "message": url}]
        if method == "POST" and rid is None:
            return self.create(obj, body, who, scopes)
        if method == "PATCH" and rid:
            return self.update(obj, rid, body, who, scopes)
        if method == "GET" and rid:
            return self.get(obj, rid)
        return 405, [{"errorCode": "METHOD_NOT_ALLOWED", "message": f"{method} {url}"}]

    # SOSL.

    def search(self, term: str, rest: str) -> list[Record]:
        """The org's records a SOSL search finds: every word of the term (* and ? as wildcards) in the field group
        named before RETURNING, in the objects RETURNING names with the fields it lists, or every object by Id."""
        words = [
            re.compile(re.escape(w).replace(r"\*", r"\w*").replace(r"\?", r"\w"), re.IGNORECASE)
            for w in term.replace('"', " ").split()
        ]
        group = re.search(r"\bIN\s+(NAME|EMAIL|PHONE)\s+FIELDS\b", rest, re.IGNORECASE)
        returning = re.search(r"\bRETURNING\b(.*)", rest, re.IGNORECASE | re.DOTALL)
        wanted = (
            [
                (name, re.split(r"\s+(?:WHERE|ORDER\s+BY|LIMIT|OFFSET)\b", fields, flags=re.IGNORECASE)[0])
                for name, fields in re.findall(r"(\w+)\s*(?:\(([^)]*)\))?", returning[1])
            ]
            if returning
            else [(o, "Id") for o in FIELDS]
        )
        found: list[Record] = []
        for name, listed in wanted:
            obj = self.object_name(name)
            if obj is None or not words:
                continue
            for record in self.records.get(obj, {}).values():
                text = " ".join(self._searchable(obj, record, group[1].upper() if group else "ALL"))
                if all(w.search(text) for w in words):
                    out: Record = {"attributes": self.attributes(obj, record)}
                    for f in [f.strip() for f in listed.split(",") if f.strip()] or ["Id"]:
                        self.put(out, obj, record, f)
                    found.append(out)
        return found

    def _searchable(self, obj: str, record: Record, group: str) -> list[str]:
        kinds = dict(FIELDS.get(obj, ()))

        def searched(name: str) -> bool:
            if group == "NAME":
                return name in ("Name", "FirstName", "LastName", "Subject", "CaseNumber")
            if group in ("EMAIL", "PHONE"):
                return kinds.get(name) == group.lower()
            return kinds.get(name, "string") in ("string", "textarea", "email", "phone", "picklist")

        return [v for k, v in record.items() if isinstance(v, str) and searched(k)]


def _label(name: str) -> str:
    if name in LABELS:
        return LABELS[name]
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)
    return spaced[:-3] + " ID" if spaced.endswith(" Id") else spaced


def _halted(ref: str) -> dict[str, Any]:
    return {
        "body": [{"errorCode": "PROCESSING_HALTED", "message": _HALTED}],
        "httpHeaders": {},
        "httpStatusCode": 400,
        "referenceId": ref,
    }


def _resolved(value: Any, done: dict[str, Any]) -> Any:
    """A subrequest's url or body with each @{referenceId.path} replaced by that earlier answer's value; a string that
    is one reference whole takes the value's own type. An unknown reference raises LookupError."""
    if isinstance(value, str):
        whole = _REFERENCE.fullmatch(value)
        if whole:
            return _dereference(whole[1], done)
        return _REFERENCE.sub(lambda m: str(_dereference(m[1], done)), value)
    if (fields := _object(value)) is not None:
        return {k: _resolved(v, done) for k, v in fields.items()}
    if isinstance(value, list):
        return [_resolved(v, done) for v in cast("list[Any]", value)]
    return value


def _dereference(expression: str, done: dict[str, Any]) -> Any:
    head, *path = expression.split(".")
    if head not in done:
        raise LookupError(expression)
    value: Any = done[head]
    for step in path:
        matched = re.fullmatch(r"(\w+)((?:\[\d+\])*)", step)
        try:
            if matched is None:
                raise LookupError(expression)
            value = value[matched[1]]
            for index in re.findall(r"\[(\d+)\]", matched[2]):
                value = value[int(index)]
        except (KeyError, IndexError, TypeError) as e:
            raise LookupError(expression) from e
    return value


def _serve(app: Any, address: str, cert: Path, key: Path) -> tuple[Any, int]:
    import uvicorn

    with socket.socket() as s:
        s.bind((address, 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(app, host=address, port=port, log_level="warning", ssl_certfile=str(cert), ssl_keyfile=str(key))
    )
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    return server, port


@contextmanager
def salesforce(token_expiry_s: int = 300) -> Generator[dict[str, Any]]:
    """The fake on https; yields tools-service's settings to reach it, the hosts and range to list, the OAuth
    addresses a connection names, the API's base, `fake` (its state), and `sign_in(url, username)`, which plays a
    person's browser through the server's sign-in page and returns the code and state it redirects back with."""
    with oauth_server(token_expiry_s) as upstream, tempfile.TemporaryDirectory() as tmp:
        cert, key = _certificate(Path(tmp))
        address = private_address()
        fake = Salesforce(upstream)
        server, port = _serve(fake.app(), address, cert, key)
        try:

            def sign_in(authorize_url: str, username: str) -> dict[str, str]:
                url = urlsplit(authorize_url)
                target = f"https://{address}:{port}{url.path}?{url.query}"
                # Reached by address with the sign-in host named in Host, so the name check cannot pass; tools-service,
                # which does verify, reaches the same certificate by name through OPS_EGRESS_RESOLVE.
                with httpx.Client(verify=False, headers={"Host": url.hostname or LOGIN_HOST}, timeout=30) as browser:
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
                        dict.fromkeys((LOGIN_HOST, *INSTANCES.values()), f"{address}:{port}")
                    ),
                },
                "hosts": [LOGIN_HOST, *INSTANCES.values()],
                "sandbox_login": SANDBOX_ISSUER,
                # Where the Salesforce plugin signs in to each org: its company address (My Domain), one of the
                # places the plugin takes.
                "login_url": f"https://{API_HOST}/services/oauth2",
                "sandbox_login_url": f"https://{SANDBOX_HOST}/services/oauth2",
                "sandbox_base": f"https://{SANDBOX_HOST}",
                "eu_login_url": f"https://{EU_HOST}/services/oauth2",
                "eu_base": f"https://{EU_HOST}",
                "range": f"{address}/32",
                "authorize_url": f"{ISSUER}/authorize",
                "token_url": f"{ISSUER}/token",
                "revoke_url": f"https://{LOGIN_HOST}/services/oauth2/revoke",
                "api_base": f"https://{API_HOST}",
                "case_url": f"https://{API_HOST}{API}/sobjects/Case/{CASE_ID}",
                "userinfo_url": f"https://{API_HOST}/services/oauth2/userinfo",
                "control": f"https://{address}:{port}/_control/state",
                "ca": str(cert),
                "fake": fake,
                "sign_in": sign_in,
            }
        finally:
            server.should_exit = True


if __name__ == "__main__":
    # A parent that stops this script with SIGTERM still gets the OAuth server's container removed: SystemExit runs the
    # context managers' cleanup, which the default SIGTERM action skips.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with salesforce() as sf:
        shown = {k: v for k, v in sf.items() if k not in ("fake", "sign_in")}
        print(json.dumps({**shown, "owner": os.getpid()}), flush=True)
        sys.stdin.read()
