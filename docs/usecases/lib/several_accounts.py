"""Shared setup for the several-accounts use cases (uc-691 to uc-705): a team with two live Salesforce orgs.

platform-service signs the seeded people in; tools-service runs with plugins on, the Salesforce plugin (OPS_PLUGINS_REPO,
else the ops-ai-plugins repository beside ops-ai) and Ops AI's own app for it (OPS_PLUGIN_CLIENTS), against the fake
Salesforce (fake_salesforce.py), whose production org (kestrel), second production org (kestrel-eu) and sandbox (uat)
each sign in at their own My Domain and answer only their own tokens. Security lists the fake's private range only.
Every tool call is a gateway call as agents-service makes it: a run in team_ops, acting for nobody or, with
`acting_for`, carrying the acting-for token platform-service signs for that person. No model call.
"""

from __future__ import annotations

import json
import os
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
from fake_salesforce import salesforce
from usecase_harness import (
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    bearer,
    data,
    platform,
    service_headers,
    signed_in,
    tools,
)
from usecase_harness import ROOT as REPO

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
PLUGINS = Path(os.environ.get("OPS_PLUGINS_REPO") or REPO.parent / "ops-ai-plugins") / "plugins"
SALESFORCE = PLUGINS / "salesforce/src/ops_plugin_salesforce"
SF = "plugin:opsai.salesforce"
CLIENTS = {"opsai.salesforce": {"id": "ops-ai-acme", "secret": "acme-app"}}
QUERY = "SELECT Id, CaseNumber, Status FROM Case WHERE CaseNumber = '00044818'"
QUERY_PATH = "/query"
PRIYA, MAYA = "p.shah@harborpine.example", "m.okafor@harborpine.example"


@dataclass
class Rig:
    sf: dict[str, Any]
    inner: httpx.Client
    gw: httpx.Client
    sam: dict[str, str]
    priya: dict[str, str]
    maya: dict[str, str]
    tenant: str
    ids: dict[str, str] = field(default_factory=dict[str, str])

    def headers(self, team: str = "team_ops", acting_for: str | None = None) -> dict[str, str]:
        """A service call as agents-service makes it for a run in `team`, acting for `acting_for` (an email) or for
        nobody."""
        out = service_headers("tools", tenant=self.tenant, service="agents", team=team) | {"X-Team-Id": team}
        if acting_for:
            minted = self.inner.post(
                "/v1/acting-for-tokens",
                json={"email": acting_for},
                headers=service_headers("platform", tenant=self.tenant, service="agents", team=team),
            )
            out["X-Acting-For"] = str((data(minted) or {}).get("token") or "")
        return out

    def call(
        self,
        *,
        accounts: dict[str, str] | None = None,
        account: str | None = None,
        environment: str = "live",
        team: str = "team_ops",
        acting_for: str | None = None,
        tool: str = "salesforce_query",
        args: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """salesforce_query (or `tool`) through the gateway, naming `accounts` (app id to name) or the older single
        `account` string."""
        context: dict[str, Any] = {"environment": environment}
        if accounts is not None:
            context["accounts"] = accounts
        if account is not None:
            context["account"] = account
        body = {"tool": tool, "input": args or {"q": QUERY}, "key": uuid4().hex, "runContext": context}
        return self.gw.post("/v1/calls", json=body, headers=self.headers(team, acting_for))

    def hosts(self, since: int) -> list[str]:
        """The org host of each query the fake answered after `since` calls; the test each sign-in runs, which may
        land later, is left out."""
        return [c["host"] for c in self.sf["fake"].state()["calls"][since:] if c["path"].endswith(QUERY_PATH)]

    def calls_so_far(self) -> int:
        return len(self.sf["fake"].state()["calls"])

    def sign_in(self, who: dict[str, str], account: str, user: str, as_: str = "team") -> tuple[str, httpx.Response]:
        """Plays the browser through `account`'s sign-in (the team's, or `self` for the person's own); the address the
        sign-in opened, and its answer."""
        started = self.gw.post(f"/v1/apps/{SF}/accounts/{account}/sign-in", json={"account": as_}, headers=who)
        return self.finish(who, str((data(started) or {}).get("authorizeUrl") or ""), user)

    def finish(self, who: dict[str, str], opened: str, user: str) -> tuple[str, httpx.Response]:
        back = self.sf["sign_in"](opened, user) if opened else {}
        done = self.gw.post(
            "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=who
        )
        return opened, done

    def row(self, who: dict[str, str], account: str) -> dict[str, Any]:
        """The account's row on the app's Accounts list."""
        page = data(self.gw.get(f"/v1/apps/{SF}", headers=who)) or {}
        return next((a for a in page.get("accounts") or [] if a.get("id") == account), {})

    def found(self, who: dict[str, str], account: str) -> dict[str, str]:
        """Where an account signs in and what its sign-in found, as its row shows them."""
        return {f"{v['kind']}:{v['name']}": str(v["value"]) for v in self.row(who, account).get("signInValues") or []}

    def logged(self, r: httpx.Response) -> dict[str, Any]:
        """The call log row of a gateway call's answer: its environment and the account it signed in with."""
        call_id = str((r.json().get("data") or {}).get("callId") or "") if r.status_code == 200 else ""
        if not call_id:
            return {}
        got = self.gw.get(f"/v1/executions/{call_id}", headers=self.priya)
        return dict(data(got) or {})


def code_of(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("code") or "")
    except ValueError:
        return ""


@contextmanager
def rig(note: str) -> Generator[Rig]:
    """The services and people; Salesforce is not yet turned on."""
    with ExitStack() as stack:
        sf = stack.enter_context(salesforce())
        api, inner = stack.enter_context(platform())
        plugins = {
            "OPS_PLUGINS": "true",
            "OPS_PLUGIN_PATHS": json.dumps([str(SALESFORCE)]),
            "OPS_PLUGIN_CLIENTS": json.dumps(CLIENTS),
        }
        gw = stack.enter_context(
            tools({**sf["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
        )
        sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
        session = signed_in(api, PRIYA)
        tenant = str((session.get("principal") or {}).get("tenantId") or session.get("tenantId") or "")
        gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": note}, headers=sam)
        yield Rig(
            sf=sf,
            inner=inner,
            gw=gw,
            sam=sam,
            priya=bearer(session, "team_ops"),
            maya=bearer(signed_in(api, MAYA), "team_ops"),
            tenant=tenant,
        )


def retail_on(r: Rig, sign_in: str = "team") -> httpx.Response:
    """Priya turns Salesforce on through Ops AI's app as "Retail org" at the production org's My Domain and signs the
    team account in; `r.ids["retail"]` is its id."""
    body = {
        "enabled": True,
        "signIn": sign_in,
        "accountName": "Retail org",
        "settings": {"login_url": r.sf["login_url"]},
    }
    on = r.gw.put(f"/v1/apps/{SF}/team", json=body, headers=r.priya)
    r.ids["retail"] = str((data(on) or {}).get("connectionId") or "con_missing")
    r.sign_in(r.priya, r.ids["retail"], "kestrel.integration")
    return on


def add_org(r: Rig, name: str, login_url: str, user: str, *, sandbox: bool = False) -> tuple[httpx.Response, str]:
    """Priya adds another account of Salesforce at `login_url`, named `name`, and signs it in; the add's answer and the
    address its sign-in opened."""
    made = r.gw.post(
        f"/v1/apps/{SF}/accounts",
        json={"name": name, "sandbox": sandbox, "settings": {"login_url": login_url}},
        headers=r.priya,
    )
    r.ids[name] = str((data(made) or {}).get("id") or "con_missing")
    opened, _ = r.sign_in(r.priya, r.ids[name], user)
    return made, opened


GITHUB = PLUGINS / "github/src/ops_plugin_github"
GH = "plugin:opsai.github"
GH_CLIENTS = {"opsai.github": {"id": "ops-ai-gh", "secret": "gh-app"}}


@dataclass
class GitRig:
    gh: dict[str, Any]
    inner: httpx.Client
    gw: httpx.Client
    priya: dict[str, str]
    maya: dict[str, str]
    tenant: str
    ids: dict[str, str] = field(default_factory=dict[str, str])

    def call(self, accounts: dict[str, str] | None = None, acting_for: str | None = None) -> httpx.Response:
        """github_list_issues on brightloop/dispatch in a live run in team_ops, naming `accounts` when given."""
        context: dict[str, Any] = {"environment": "live", **({"accounts": accounts} if accounts else {})}
        body = {
            "tool": "github_list_issues",
            "input": {"owner": "brightloop", "repo": "dispatch"},
            "key": uuid4().hex,
            "runContext": context,
        }
        headers = service_headers("tools", tenant=self.tenant, service="agents", team="team_ops")
        if acting_for:
            minted = self.inner.post(
                "/v1/acting-for-tokens",
                json={"email": acting_for},
                headers=service_headers("platform", tenant=self.tenant, service="agents", team="team_ops"),
            )
            headers["X-Acting-For"] = str((data(minted) or {}).get("token") or "")
        return self.gw.post("/v1/calls", json=body, headers=headers | {"X-Team-Id": "team_ops"})

    def finish(self, who: dict[str, str], opened: str) -> httpx.Response:
        back = self.gh["sign_in"](opened) if opened else {}
        return self.gw.post(
            "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=who
        )

    def sign_in(self, who: dict[str, str], account: str, as_: str = "team") -> tuple[str, httpx.Response]:
        started = self.gw.post(f"/v1/apps/{GH}/accounts/{account}/sign-in", json={"account": as_}, headers=who)
        opened = str((data(started) or {}).get("authorizeUrl") or "")
        return opened, self.finish(who, opened)


def issues(r: httpx.Response) -> list[int]:
    got = data(r) if r.status_code == 200 else None
    out = dict((got or {}).get("output") or {}) if isinstance(got, dict) else {}
    return [int(i["number"]) for i in out.get("issues") or []]


@contextmanager
def git_rig(note: str) -> Generator[GitRig]:
    """The fake GitHub, platform-service and tools-service with the GitHub plugin and Ops AI's app for it; GitHub is
    not yet turned on."""
    from fake_github import github  # only the GitHub use cases need it

    with ExitStack() as stack:
        gh = stack.enter_context(github())
        api, inner = stack.enter_context(platform())
        plugins = {
            "OPS_PLUGINS": "true",
            "OPS_PLUGIN_PATHS": json.dumps([str(GITHUB)]),
            "OPS_PLUGIN_CLIENTS": json.dumps(GH_CLIENTS),
        }
        gw = stack.enter_context(
            tools({**gh["settings"], **AUTH, **plugins, "OPS_CONSOLE_URL": "https://console.acme.test"})
        )
        sam = bearer(signed_in(api, "s.adeyemi@harborpine.example"), "team_security")
        session = signed_in(api, PRIYA)
        tenant = str((session.get("principal") or {}).get("tenantId") or session.get("tenantId") or "")
        gw.post("/v1/egress/ranges", json={"value": gh["range"], "note": note}, headers=sam)
        yield GitRig(
            gh=gh,
            inner=inner,
            gw=gw,
            priya=bearer(session, "team_ops"),
            maya=bearer(signed_in(api, MAYA), "team_ops"),
            tenant=tenant,
        )


def github_on(r: GitRig, sign_in: str = "team") -> httpx.Response:
    """Priya turns GitHub on as "Platform server" at github.test, its API at the fake's, and signs the team in."""
    settings = {"web_url": r.gh["public_url"], "api_url": r.gh["api_url"]}
    body = {"enabled": True, "signIn": sign_in, "accountName": "Platform server", "settings": settings}
    on = r.gw.put(f"/v1/apps/{GH}/team", json=body, headers=r.priya)
    r.ids["public"] = str((data(on) or {}).get("connectionId") or "con_missing")
    r.sign_in(r.priya, r.ids["public"])
    return on
