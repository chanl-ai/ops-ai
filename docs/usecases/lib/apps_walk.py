"""The Apps use cases' shared stack and calls.

One stack per script: platform-service with the dev seed's own roles, tools-service with plugins on and the nine test
plugins of services/tools-service/tests/plugin_kinds, and the fake system of fake_multi_auth.py. Every test plugin is
installed, so every team sees it, and the fake's hosts are allowed before a script's first step.

Every call goes through the Apps API: an app under `/v1/apps/{app}` and each of its accounts under
`/v1/apps/{app}/accounts/{id}` (a plugin's app is `plugin:<id>`, a custom app's id is its first account's). A check whose
behaviour is not built yet names the task it waits on in its detail (`target: waits on D2`), so a failing run says
which steps are targets.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from fake_multi_auth import multi_auth
from usecase_harness import (
    AGENTS_PORT,
    DOCUMENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    TOOLS_PORT,
    as_role,
    data,
    platform,
    service_headers,
    tools,
)

AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
KINDS = ROOT / "services/tools-service/tests/plugin_kinds"
PLUGINS = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps(sorted(str(p) for p in KINDS.glob("kinds_*")))}
ROLES = ("admin", "builder", "approver", "viewer", "security", "platform")
# Each role's team in the dev seed (services/platform-service/seed/dev-roles.json).
TEAM_OF = dict.fromkeys(("admin", "builder", "approver", "viewer"), "team_ops") | {
    "security": "team_security",
    "platform": "team_platform",
}


def target(task: str) -> str:
    """The detail of a check whose behaviour waits on work not built yet."""
    return f"target: waits on {task}"


def app_path(app: str) -> str:
    """`/v1/apps/<app>`; an app id may carry a colon (`plugin:test.person`, `builtin:files`)."""
    return f"/v1/apps/{quote(app, safe=':')}"


def account_path(app: str, account: str) -> str:
    """`/v1/apps/<app>/accounts/<account>`: an account is found only under its own app."""
    return f"{app_path(app)}/accounts/{quote(account, safe='')}"


@dataclass
class Walk:
    api: httpx.Client
    inner: httpx.Client
    gw: httpx.Client
    m: dict[str, Any]
    who: dict[str, dict[str, str]]
    tenant: str
    seen: list[str] = field(default_factory=list)

    def kept(self, r: httpx.Response) -> httpx.Response:
        self.seen.append(r.text)
        return r

    def first(self, method: str, paths: list[str], role: str, **kw: Any) -> httpx.Response:
        """The first of `paths` that exists (not 404 for a missing route, not 405)."""
        r = httpx.Response(404)
        for p in paths:
            r = self.kept(self.gw.request(method, p, headers=self.who[role], **kw))
            missing = r.status_code == 405 or (r.status_code == 404 and '"Not Found"' in r.text)
            if not missing:
                return r
        return r

    def credential(self, role: str, plugin: str, client_id: str, client_secret: str) -> str:
        """The team's own OAuth client for `plugin`, made under Credentials with no account; returns its id, which a
        turn-on or an account names as credentialId."""
        r = self.kept(
            self.gw.post(
                "/v1/app-credentials",
                headers=self.who[role],
                json={"app": f"plugin:{plugin}", "clientId": client_id, "clientSecret": client_secret},
            )
        )
        return str((data(r) or {}).get("id") or "cred_missing") if r.status_code == 201 else "cred_missing"

    def turn_on(self, role: str, plugin: str, **body: Any) -> str:
        """Turns `plugin` on for the role's team; returns the team account's id (its connection)."""
        r = self.kept(
            self.gw.put(f"/v1/apps/plugin:{plugin}/team", headers=self.who[role], json={"enabled": True, **body})
        )
        return str((data(r) or {}).get("connectionId") or "con_missing") if r.status_code == 200 else "con_missing"

    def test(self, role: str, app: str, account: str, *, as_who: str = "self") -> dict[str, Any]:
        """Test connection on one account of `app`, as the role or (`as_who="team"`) as the team account."""
        r = self.kept(
            self.gw.post(f"{account_path(app, account)}/test", headers=self.who[role], json={"account": as_who})
        )
        return dict((data(r) or {}).get("health") or {"status": f"http {r.status_code}", "text": r.text[:200]})

    def sign_in(self, role: str, app: str, account: str, user: str) -> int:
        """Plays a person's browser through the fake's sign-in page for their own account on `account`."""
        started = self.kept(self.gw.post(f"{account_path(app, account)}/sign-in", headers=self.who[role], json={}))
        url = (data(started) or {}).get("authorizeUrl", "") if started.status_code == 200 else ""
        back = self.m["sign_in"](url, user) if url else {}
        done = self.kept(
            self.gw.post(
                f"{account_path(app, account)}/sign-in/complete",
                headers=self.who[role],
                json={"state": back.get("state", ""), "code": back.get("code", "")},
            )
        )
        return done.status_code

    def call(
        self, tool: str, *, team: str = "team_ops", args: dict[str, Any] | None = None, acting_for: str | None = None
    ) -> httpx.Response:
        """A gateway call as agents-service makes it for a run in `team`; a read, so it runs at once. With
        `acting_for` (an email) it carries the acting-for token platform-service signs for that person, as a run a
        person started does; the gateway never takes the person from the body."""
        headers = service_headers("tools", tenant=self.tenant, service="agents", team=team) | {"X-Team-Id": team}
        if acting_for:
            minted = self.inner.post(
                "/v1/acting-for-tokens",
                json={"email": acting_for},
                headers=service_headers("platform", tenant=self.tenant, service="agents", team=team),
            )
            headers["X-Acting-For"] = str((data(minted) or {}).get("token") or "")
        body = {"tool": tool, "input": args or {}, "key": uuid4().hex, "runContext": {"environment": "production"}}
        return self.kept(self.gw.post("/v1/calls", json=body, headers=headers))


@contextmanager
def apps_stack(tools_env: dict[str, str] | None = None, ops_ai_apps: dict[str, str] | None = None) -> Generator[Walk]:
    """The stack with every test plugin installed. `ops_ai_apps` names, per plugin, the fake's OAuth client that is
    Ops AI's own app for it, passed to tools-service as install config (OPS_PLUGIN_CLIENTS)."""
    with ExitStack() as stack:
        m = stack.enter_context(multi_auth())
        api, inner = stack.enter_context(platform())
        apps = ops_ai_apps or {}
        # Ops AI's own app per plugin is the install's, from its config, as a deployment sets it.
        clients = {p: {"id": c, "secret": m["clients"][c]} for p, c in apps.items()}
        installed = {"OPS_PLUGIN_CLIENTS": json.dumps(clients)} if clients else {}
        gw = stack.enter_context(tools({**m["settings"], **AUTH, **PLUGINS, **installed, **(tools_env or {})}))
        who = {role: as_role(api, role, TEAM_OF[role]) for role in ROLES}
        me = data(api.get("/v1/me", headers=who["admin"])) or {}
        tenant = str(me.get("tenantId") or (me.get("principal") or {}).get("tenantId") or "")
        walk = Walk(api=api, inner=inner, gw=gw, m=m, who=who, tenant=tenant)
        for h in m["hosts"]:
            gw.post("/v1/egress/hosts", json={"value": h, "note": "apps"}, headers=who["security"])
        gw.post("/v1/egress/ranges", json={"value": m["range"], "note": "apps"}, headers=who["security"])
        yield walk


def sdk_op(ops: Any, service: str, name: str) -> Callable[..., Any] | None:
    """The generated SDK operation `ops.raw.<service>.<name>`, or None while the route it calls is not built."""
    return getattr(getattr(ops.raw, service), name, None)


def signed_sdk(role: str) -> Any:
    """The Python SDK in sdk/python signed in as the role's seeded person, acting in its team, on this run's ports."""
    sys.path.insert(0, str(ROOT / "sdk" / "python" / "src"))
    from ops_ai import OpsAI

    sys.path.insert(0, str(ROOT / "scripts"))
    from api_as import roles

    services = {
        "platform": f"http://127.0.0.1:{PLATFORM_PORT}",
        "tools": f"http://127.0.0.1:{TOOLS_PORT}",
        "agents": f"http://127.0.0.1:{AGENTS_PORT}",
        "documents": f"http://127.0.0.1:{DOCUMENTS_PORT}",
    }
    return OpsAI.sign_in(
        roles()[role], "northfield-demo", team=TEAM_OF[role], base_url="http://127.0.0.1", services=services
    )


_TOKENS = Path(tempfile.mkdtemp(prefix="apps-cli-tokens-"))


def ops_cli(role: str, *args: str, stdin: str | None = None) -> tuple[int, Any]:
    """`ops <args> --as <role> --json` as a developer runs it from the repo, signed in like `make api` against this
    run's services, with `stdin` as its input (how a secret is given). Returns the exit code and the parsed answer, or
    the raw text when it is not JSON."""
    env = {
        **os.environ,
        "OPS_PLATFORM_PORT": str(PLATFORM_PORT),
        "OPS_TOOLS_PORT": str(TOOLS_PORT),
        "OPS_AGENTS_PORT": str(AGENTS_PORT),
        "OPS_DOCUMENTS_PORT": str(DOCUMENTS_PORT),
        "OPS_API_TOKENS": str(_TOKENS),
    }
    p = subprocess.run(
        ["uv", "run", "--quiet", "ops", *args, "--as", role, "--json"],
        cwd=ROOT, env=env, input=stdin, capture_output=True, text=True, timeout=180, check=False,
    )  # fmt: skip
    try:
        return p.returncode, json.loads(p.stdout)
    except ValueError:
        return p.returncode, (p.stdout + p.stderr)[-400:]
