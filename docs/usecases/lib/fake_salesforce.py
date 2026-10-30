"""A fake Salesforce for per-person sign-in use cases (c-558): its sign-in served by navikt's mock-oauth2-server, a
standard OAuth 2.0 server run in Docker, and a REST API that accepts only that server's tokens.

Both answer on https on this machine's private address with one self-signed certificate: `login.salesforce.test`
fronts the OAuth server and `kestrel.my.salesforce.test` serves the API, as a company's My Domain does. tools-service
reaches them as any outside system: the use case lists the hosts and the private range, gives tools-service the
certificate as its CA (OPS_EGRESS_CA_FILE) and maps the names to the address and port (OPS_EGRESS_RESOLVE, dev only).

The API checks each bearer token's signature against the server's published keys, its issuer, audience and expiry, and
records the token's subject as the editor of a case, so a use case can tell whose account a call used. The token
answer carries the scopes asked for at sign-in, as Salesforce's does, and an operation that needs a scope the token was
not granted is refused with 403.

Run as a script, it serves until stdin closes and prints one JSON line with what a Node ui use case needs.
"""

from __future__ import annotations

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
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from fake_bank_https import private_address

from ops_service_kit import harness_containers

LOGIN_HOST = "login.salesforce.test"
API_HOST = "kestrel.my.salesforce.test"
ISSUER_ID = "salesforce"
ISSUER = f"https://{LOGIN_HOST}/{ISSUER_ID}"
AUDIENCE = "salesforce-api"
IMAGE = "ghcr.io/navikt/mock-oauth2-server:2.1.10"
API = "/services/data/v61.0"
CASE_ID = "5003000000D8cuIAAR"
# A second case the Salesforce plugin's use case works (c-564); writing it needs no extra scope, as in Salesforce.
PLUGIN_CASE_ID = "5003000000D8cuJAAR"
ARTICLES = "Knowledge__kav"
# Articles per listing page, so a listing of the three seeded articles takes two pages and one nextRecordsUrl.
PAGE_SIZE = 2
# The scope an operation that writes a case needs, beyond `api`; a token signed in without it is refused (US4).
WRITE_SCOPE = "cases.write"
# One account's data for the query tools (c-581): three open escalated cases, one escalated case in the recycle bin,
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
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(LOGIN_HOST), x509.DNSName(API_HOST)]), critical=False)
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
        "tokenCallbacks": [
            {
                "issuerId": ISSUER_ID,
                "tokenExpiry": token_expiry_s,
                "requestMappings": [{"requestParam": "grant_type", "match": "*", "claims": {"aud": [AUDIENCE]}}],
            }
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
        # Each article or attachment read by id, so a use case can tell an unchanged article was not fetched again.
        self.fetched: list[str] = []
        # A listing's next-page locators, as Salesforce keeps a query cursor server-side.
        self._locators: dict[str, str] = {}
        # Cases the query tools read (c-581), by id; the deleted one only through queryAll.
        self.seeded: dict[str, dict[str, Any]] = {c["Id"]: dict(c) for c in SEEDED_CASES}
        # Set through /_control/mode: answer the next API request 401, answer the listing's second page 429 once,
        # or name a host outside Salesforce as the token's instance_url.
        self.fail_next: int | None = None
        self.limit_second_page = False
        self.bad_instance = False
        self.edits: list[dict[str, Any]] = []
        self.refused: list[str] = []
        self.revoked: list[str] = []
        # The OAuth app each token exchange came from, (client id, client secret): which app a team's sign-in used.
        self.clients: list[tuple[str, str]] = []
        # The scopes asked for at sign-in, by the code the server returned, then by the access token issued for it.
        self._scope_by_code: dict[str, str] = {}
        self._scope_by_token: dict[str, str] = {}
        self._pending: dict[str, str] = {}
        self._jwks = jwt.PyJWKClient(f"{upstream}/{ISSUER_ID}/jwks")

    def app(self) -> Any:
        from starlette.applications import Starlette  # noqa: PLC0415 - the agents-service environment has it
        from starlette.routing import Route  # noqa: PLC0415

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST", "PATCH"])])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse, Response  # noqa: PLC0415

        host = (request.headers.get("host") or "").split(":")[0]
        body = await request.body()
        if request.url.path.startswith("/_control/"):
            if request.method == "POST":
                self._control(request.url.path, json.loads(body or b"{}"))
            return JSONResponse(self.state())
        if host == LOGIN_HOST:
            return await self._login(request, body)
        auth = request.headers.get("authorization", "")
        token = auth[7:] if auth.startswith("Bearer ") else ""
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=AUDIENCE, issuer=ISSUER)
        except jwt.PyJWTError as e:
            self.refused.append(type(e).__name__)
            return JSONResponse([{"errorCode": "INVALID_SESSION_ID", "message": str(e)}], 401)
        who = str(claims["sub"])
        scopes = set(self._scope_by_token.get(token, "").split())
        path = request.url.path
        if path == "/services/oauth2/userinfo":
            return JSONResponse({"preferred_username": who, "organization_id": "00Dkestrel"})
        if self.fail_next is not None:
            status, self.fail_next = self.fail_next, None
            code = "REQUEST_LIMIT_EXCEEDED" if status == 429 else "INVALID_SESSION_ID"
            return JSONResponse([{"errorCode": code}], status)
        found = self._query_tools(request, path)
        if found is not None:
            return found
        if path == f"{API}/query":
            q = request.query_params.get("q", "")
            self.queries.append(q)
            if ARTICLES in q:
                return JSONResponse(self._articles_page(q, 0))
            if PLUGIN_CASE_ID in q or "00044818" in q:
                return JSONResponse({"totalSize": 1, "done": True, "records": [dict(self.cases[PLUGIN_CASE_ID])]})
            return JSONResponse({"totalSize": 1, "done": True, "records": [dict(self.case)]})
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

    def _query_tools(self, request: Any, path: str) -> Any:
        """The Salesforce calls the plugin's query tools make (c-581), or None for any other path."""
        from starlette.responses import JSONResponse  # noqa: PLC0415

        params = request.query_params
        # The query tools filter cases by status; uc-564's case lookups by number keep their own answer below.
        if path in (f"{API}/query", f"{API}/queryAll") and re.search(
            r"FROM Case WHERE Status = '", params.get("q", "")
        ):
            q = params["q"] + (" ALL" if path.endswith("queryAll") else "")
            self.queries.append(params["q"])
            return JSONResponse(self._cases_page(q, 0))
        if path == f"{API}/search":
            self.queries.append(params.get("q", ""))
            term = re.search(r"FIND \{(.*)\} IN ALL FIELDS", params.get("q", ""))
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
        page = rows[offset : offset + PAGE_SIZE]
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
        from starlette.responses import JSONResponse, Response  # noqa: PLC0415

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
            if body.get("expireLocators"):
                # Salesforce drops a query locator after a while; the next page asked of it is refused.
                self._locators.clear()
        elif path.endswith("/articles"):
            for item in body.get("change", []):
                self.articles[item["Id"]].update(item)

    async def _login(self, request: Any, body: bytes) -> Any:
        from starlette.responses import JSONResponse, Response  # noqa: PLC0415

        path = request.url.path
        if path.endswith("/revoke"):
            self.revoked.append(parse_qs(body.decode()).get("token", [""])[0])
            return Response(status_code=200)
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")}
        headers |= {"Host": LOGIN_HOST, "X-Forwarded-Proto": "https", "X-Forwarded-Port": "443"}
        query = str(request.url.query)
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
            answer["instance_url"] = "https://evil.example" if self.bad_instance else f"https://{API_HOST}"
            self._scope_by_token[answer["access_token"]] = scope
            if answer.get("refresh_token"):
                self._scope_by_token[answer["refresh_token"]] = scope
            return JSONResponse(answer, 200)
        return Response(r.content, status_code=r.status_code, headers=out)

    def state(self) -> dict[str, Any]:
        return {
            "case": dict(self.case),
            "cases": {k: dict(v) for k, v in self.cases.items()},
            "queries": list(self.queries),
            "edits": list(self.edits),
            "fetched": list(self.fetched),
            "refused": list(self.refused),
            "revoked": list(self.revoked),
            "clients": list(self.clients),
        }


def _when(text: str) -> datetime | None:
    """A Salesforce or ISO date and time as UTC, or None."""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _serve(app: Any, address: str, cert: Path, key: Path) -> tuple[Any, int]:
    import uvicorn  # noqa: PLC0415

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
                    "OPS_EGRESS_RESOLVE": json.dumps({LOGIN_HOST: f"{address}:{port}", API_HOST: f"{address}:{port}"}),
                },
                "hosts": [LOGIN_HOST, API_HOST],
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
