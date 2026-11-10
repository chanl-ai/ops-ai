"""SharePoint and Confluence for the knowledge-source use cases, served on https on this machine's private address under
the names the plugins call, with one certificate for all of them.

The plugins' own fakes answer: `FakeGraph` (plugins/sharepoint/tests/fake_graph.py) as graph.microsoft.com and the
tenant's SharePoint host, `FakeConfluence` (plugins/confluence/tests/fake_confluence.py) as the Confluence Cloud site
and Atlassian's media host, both from the plugins checkout (OPS_PLUGINS_REPO, else ops-ai-plugins beside this one).
login.microsoftonline.com is fake_token_endpoint's code sign-in for one Entra app registered with a client secret.
Graph answers only a token that endpoint issued and Confluence only the basic credential the run made, so a call that
gets an answer carried the team's sign-in. The client secret and the Confluence API token are made per run and never
printed.

A sites search for FAILING_QUERY answers 503, as Graph does while SharePoint is unavailable, so a picker's error state
is the plugin's real failure path. tools-service reaches all of it as any outside system: `settings` (the CA file and
OPS_EGRESS_RESOLVE, dev only), `hosts` and `range` for Security to allow.

Run as a script for a Node ui use case: it prints one JSON line (the settings, hosts, range, plugin paths and the
fakes' ids), then for each JSON line on stdin naming a tools-service and the headers to act with
(`{"tools": url, "admin": {...}, "security": {...}}`) it connects both apps there and prints the outcome as one line.
It serves until stdin closes."""

from __future__ import annotations

import base64
import importlib
import json
import os
import secrets
import signal
import sys
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from fake_bank_https import private_address
from fake_help_site import _certificate as certificate  # pyright: ignore[reportPrivateUsage]
from fake_salesforce import _serve as serve_https  # pyright: ignore[reportPrivateUsage]
from fake_token_endpoint import TokenEndpoint

LOGIN_HOST = "login.microsoftonline.com"
GRAPH_HOST = "graph.microsoft.com"
SHAREPOINT_HOST = "contoso.sharepoint.com"
# The plugin keeps a lookup's address only on a host under .sharepoint.com, so the tenant is served under that name.
SHAREPOINT = f"https://{SHAREPOINT_HOST}"
CONFLUENCE_HOST = "acme.atlassian.test"
MEDIA_HOST = "api.media.atlassian.com"
HOSTS = [LOGIN_HOST, GRAPH_HOST, SHAREPOINT_HOST, CONFLUENCE_HOST, MEDIA_HOST]
FAILING_QUERY = "outage"
ADMIN = "it.admin@contoso.test"
SHAREPOINT_APP = "plugin:opsai.sharepoint"
CONFLUENCE_APP = "plugin:opsai.confluence"
DROPPED_HEADERS = ("content-length", "transfer-encoding", "content-encoding")

PLUGINS_REPO = Path(os.environ.get("OPS_PLUGINS_REPO") or Path(__file__).resolve().parents[4] / "ops-ai-plugins")


def plugin_path(name: str) -> Path:
    """The plugin's package folder, as OPS_PLUGIN_PATHS names it."""
    return PLUGINS_REPO / "plugins" / name / "src" / f"ops_plugin_{name}"


def _plugin_fakes() -> tuple[Any, Any]:
    """The fake_graph and fake_confluence modules from the plugins checkout."""
    for name in ("sharepoint", "confluence"):
        tests = PLUGINS_REPO / "plugins" / name / "tests"
        if not tests.is_dir():
            raise SystemExit(f"FAIL the {name} plugin's tests are not at {tests}; set OPS_PLUGINS_REPO")
        if str(tests) not in sys.path:
            sys.path.insert(0, str(tests))
    return importlib.import_module("fake_graph"), importlib.import_module("fake_confluence")


@dataclass
class Systems:
    """The running fakes and what a use case needs to reach and sign in to them."""

    address: str
    port: int
    ca_file: Path
    graph: Any
    confluence: Any
    login: TokenEndpoint
    graph_ids: Any
    client_id: str
    client_secret: str
    confluence_user: str
    confluence_token: str
    # Each request a fake refused for its credential, as host and path, never the credential.
    refused: list[str] = field(default_factory=list[str])

    @property
    def settings(self) -> dict[str, str]:
        return {
            "OPS_EGRESS_CA_FILE": str(self.ca_file),
            "OPS_EGRESS_RESOLVE": json.dumps(dict.fromkeys(HOSTS, f"{self.address}:{self.port}")),
        }

    @property
    def range(self) -> str:
        return f"{self.address}/32"

    @property
    def plugin_paths(self) -> list[str]:
        return [str(plugin_path("sharepoint")), str(plugin_path("confluence"))]

    @property
    def site_url(self) -> str:
        return str(self.confluence.site_url)

    def sign_in(self, authorize_url: str) -> dict[str, str]:
        """Plays the admin's browser through the Microsoft sign-in: the code and state it is sent back with."""
        url = urlsplit(authorize_url)
        target = f"https://{self.address}:{self.port}{url.path}?{url.query}"
        with httpx.Client(verify=False, headers={"Host": url.hostname or LOGIN_HOST}, timeout=30) as browser:
            back = browser.get(target, follow_redirects=False)
        return {k: v[0] for k, v in parse_qs(urlsplit(back.headers.get("location", "")).query).items()}

    def app(self) -> Any:
        from starlette.applications import Starlette
        from starlette.routing import Route

        return Starlette(routes=[Route("/{path:path}", self._handle, methods=["GET", "POST"])])

    async def _handle(self, request: Any) -> Any:
        from starlette.responses import JSONResponse, Response

        host = (request.headers.get("host") or "").split(":")[0]
        body = await request.body()
        path = request.url.path
        auth = request.headers.get("authorization", "")
        if host == LOGIN_HOST:
            return self._login(request, body)
        if host == GRAPH_HOST:
            if self.login.whose(auth) is None:
                self.refused.append(f"{host}{path}")
                return JSONResponse(
                    {"error": {"code": "InvalidAuthenticationToken", "message": "No valid token."}}, 401
                )
            if path.endswith("/sites") and FAILING_QUERY in request.query_params.get("search", "").lower():
                message = "SharePoint is unavailable. Try again later."
                return JSONResponse({"error": {"code": "serviceNotAvailable", "message": message}}, 503)
            fake = self.graph
        elif host == SHAREPOINT_HOST:
            fake = self.graph
        elif host in (CONFLUENCE_HOST, MEDIA_HOST):
            if host == CONFLUENCE_HOST and auth != _basic(self.confluence_user, self.confluence_token):
                self.refused.append(f"{host}{path}")
                return JSONResponse({"message": "Basic authentication with passwords is deprecated."}, 401)
            fake = self.confluence
        else:
            return JSONResponse({"error": f"no system at {host}"}, 404)
        raw = (request.scope.get("raw_path") or path.encode()).decode()
        query = request.scope.get("query_string", b"").decode()
        sent = httpx.Request(
            request.method,
            f"https://{host}{raw}" + (f"?{query}" if query else ""),
            headers=[(k, v) for k, v in request.headers.items() if k.lower() != "host"],
            content=body,
        )
        answer: httpx.Response = fake(sent)
        headers = {k: v for k, v in answer.headers.items() if k.lower() not in DROPPED_HEADERS}
        return Response(answer.content, status_code=answer.status_code, headers=headers)

    def _login(self, request: Any, body: bytes) -> Any:
        from starlette.responses import JSONResponse, Response

        path = request.url.path
        if request.method == "GET" and path.endswith("/oauth2/v2.0/authorize"):
            query = dict(request.query_params)
            return Response(status_code=302, headers={"Location": self.login.authorize(query, ADMIN)})
        if request.method == "POST" and path.endswith("/oauth2/v2.0/token"):
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            status, answer = self.login.token("entra", form, request.headers.get("authorization", ""))
            return JSONResponse(answer, status)
        return JSONResponse({"error": "invalid_request", "error_description": f"no endpoint {path}"}, 400)


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


@contextmanager
def document_systems() -> Generator[Systems]:
    """Both fakes on https, with a Microsoft app and a Confluence API token made for this run."""
    fake_graph, fake_confluence = _plugin_fakes()
    with tempfile.TemporaryDirectory(prefix="sharepoint-confluence-") as tmp:
        cert, key = certificate(Path(tmp), *HOSTS)
        address = private_address()
        login = TokenEndpoint(f"https://{LOGIN_HOST}")
        client_id = "ops-ai-contoso-knowledge"
        client_secret = secrets.token_urlsafe(24)
        login.secret_apps[client_id] = client_secret
        systems = Systems(
            address=address,
            port=0,
            ca_file=cert,
            graph=fake_graph.FakeGraph(sharepoint=SHAREPOINT),
            confluence=fake_confluence.FakeConfluence(host=CONFLUENCE_HOST),
            login=login,
            graph_ids=fake_graph,
            client_id=client_id,
            client_secret=client_secret,
            confluence_user="kb-sync@acme.test",
            confluence_token=secrets.token_urlsafe(24),
        )
        server, port = serve_https(systems.app(), address, cert, key)
        systems.port = port
        try:
            yield systems
        finally:
            server.should_exit = True


@contextmanager
def stack(folder: Path) -> Generator[tuple[Any, httpx.Client, Systems]]:
    """Both fakes, and tools-service and kb-service on the use case's ports and database with both plugins loaded:
    tools-service reaches the fakes by name, and kb-service reads each source through it."""
    from usecase_harness import TOOLS_PORT, kb, tools

    with document_systems() as systems:
        plugins = {"OPS_PLUGIN_PATHS": json.dumps(systems.plugin_paths)}
        reach = {**systems.settings, **plugins, "OPS_CONSOLE_URL": "https://console.harborpine.test"}
        kb_env = {**plugins, "OPS_TOOLS_URL": f"http://127.0.0.1:{TOOLS_PORT}"}
        with tools(settings=reach) as gw, kb(folder / "files", env=kb_env) as k:
            yield k, gw, systems


def connect(
    gw: httpx.Client,
    systems: Systems,
    admin: dict[str, str],
    security: dict[str, str],
) -> dict[str, Any]:
    """As a team sets both apps up: Security allows the systems' hosts and private range; a team admin adds the
    team's Microsoft app (its client id and secret), turns SharePoint on with it and signs the team in through
    Microsoft, then turns Confluence on with an account's email and API token and tests it. Answers each step's status
    and each app's account id; no credential, state or code is in the answer."""
    allowed = [gw.post("/v1/egress/hosts", json={"value": h, "note": "sharepoint and confluence"}, headers=security)
               for h in HOSTS]  # fmt: skip
    allowed.append(gw.post("/v1/egress/ranges", json={"value": systems.range, "note": "fakes"}, headers=security))
    out: dict[str, Any] = {"allowed": [r.status_code for r in allowed]}

    made = gw.post(
        "/v1/app-credentials",
        json={"app": SHAREPOINT_APP, "name": "Contoso Entra app", "clientId": systems.client_id,
              "clientSecret": systems.client_secret},
        headers=admin,
    )  # fmt: skip
    credential = str((_data(made) or {}).get("id") or "cred_missing")
    on = gw.put(f"/v1/apps/{SHAREPOINT_APP}/team", json={"enabled": True, "credentialId": credential}, headers=admin)
    account = str((_data(on) or {}).get("connectionId") or "con_missing")
    started = gw.post(f"/v1/apps/{SHAREPOINT_APP}/accounts/{account}/sign-in", json={"account": "team"}, headers=admin)
    opened = urlsplit(str((_data(started) or {}).get("authorizeUrl") or ""))
    back = systems.sign_in(opened.geturl()) if started.status_code == 200 else {}
    done = gw.post(
        "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=admin
    )
    out["sharepoint"] = {
        "credential": made.status_code,
        "on": on.status_code,
        "account": account,
        "opened": f"{opened.hostname}{opened.path}",
        "done": done.status_code,
        **({} if done.status_code == 200 else {"said": done.text[:300]}),
        "tokenRequests": [
            {k: r.get(k) for k in ("grant", "accepted", "refused")} for r in systems.login.token_requests
        ],
    }

    confluence = gw.put(
        f"/v1/apps/{CONFLUENCE_APP}/team",
        json={"enabled": True, "kind": "basic", "settings": {"site_url": systems.site_url},
              "credentials": {"username": systems.confluence_user, "password": systems.confluence_token}},
        headers=admin,
    )  # fmt: skip
    space_account = str((_data(confluence) or {}).get("connectionId") or "con_missing")
    tested = gw.post(
        f"/v1/apps/{CONFLUENCE_APP}/accounts/{space_account}/test", json={"account": "team"}, headers=admin
    )
    out["confluence"] = {
        "on": confluence.status_code,
        "account": space_account,
        "health": (_data(tested) or {}).get("health") if tested.status_code == 200 else tested.text[:300],
    }
    return out


def _data(res: httpx.Response) -> Any:
    try:
        return res.json().get("data")
    except ValueError:
        return None


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    with document_systems() as running:
        g = running.graph_ids
        shown = {
            "settings": running.settings,
            "hosts": HOSTS,
            "range": running.range,
            "pluginPaths": running.plugin_paths,
            "sites": {"hr": g.SITE_HR, "ops": g.SITE_OPS},
            "libraries": {"policies": g.LIB_POLICIES, "handbook": g.LIB_HANDBOOK, "runbooks": g.LIB_RUNBOOKS},
            "failingQuery": FAILING_QUERY,
        }
        print(json.dumps(shown), flush=True)
        for line in sys.stdin:
            if not line.strip():
                continue
            asked = json.loads(line)
            with httpx.Client(base_url=asked["tools"], timeout=60) as client:
                print(json.dumps(connect(client, running, asked["admin"], asked["security"])), flush=True)
