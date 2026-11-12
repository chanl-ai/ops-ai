"""The stack the template use cases share (uc-740 to uc-742): platform-service signing people in, tools-service with
the starters pack and the team MCP address on, agents-service reading tools-service. The team admin turns the starters
pack on for team_ops before the script's first step. No model call.

The starters pack is read from the plugins working copy beside this repo, or from OPS_USECASE_STARTERS_PACK."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from usecase_harness import (
    AGENTS_PORT,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    ROOT,
    TOOLS_PORT,
    agents,
    assistant_sign_in,
    bearer,
    kb,
    platform,
    signed_in,
    tools,
)

SALESFORCE_APP = "plugin:opsai.salesforce"
PACK = "opsai.starters"
SOURCE = f"plugin:{PACK}"
# A starter skill from the starters pack, with inputs (topic, doc_type).
SKILL = "doc-coauthoring"
SALESFORCE_PLUGIN = Path(
    os.environ.get(
        "OPS_USECASE_SALESFORCE_PLUGIN",
        str(ROOT.parent / "ops-ai-plugins" / "plugins" / "salesforce" / "src" / "ops_plugin_salesforce"),
    )
)
STARTERS = Path(
    os.environ.get(
        "OPS_USECASE_STARTERS_PACK",
        str(ROOT.parent / "ops-ai-plugins" / "plugins" / "starters" / "src" / "ops_plugin_starters"),
    )
)
# The public addresses the company sign-in names: this stack has no proxy, so they are the services' own ports.
PUBLIC = {
    "OPS_PLATFORM_PUBLIC_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_TOOLS_PUBLIC_URL": f"http://127.0.0.1:{TOOLS_PORT}",
}
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}


def salesforce_on(gw: Any, accounts: Any, admin: dict[str, str], sf: dict[str, Any]) -> None:
    """The team (`admin` acts in it) has the Salesforce plugin on and signed in as the fake org's integration user,
    after Security lists the fake's hosts and range. Raises SystemExit naming the step that was refused."""
    from usecase_harness import data

    sam = bearer(signed_in(accounts, "s.adeyemi@harborpine.example"), "team_security")
    for host in sf["hosts"]:
        gw.post("/v1/egress/hosts", json={"value": host, "note": "stack"}, headers=sam)
    gw.post("/v1/egress/ranges", json={"value": sf["range"], "note": "stack"}, headers=sam)
    own = {"app": SALESFORCE_APP, "clientId": "ops-ai-kestrel", "clientSecret": "kestrel-connected-app-secret"}
    credential = data(gw.post("/v1/app-credentials", json=own, headers=admin)) or {}
    team = {
        "enabled": True,
        "signIn": "team",
        "settings": {"login_url": sf["login_url"]},
        "credentialId": credential.get("id"),
    }
    turned = gw.put(f"/v1/apps/{SALESFORCE_APP}/team", json=team, headers=admin)
    connection = (data(turned) or {}).get("connectionId")
    started = gw.post(f"/v1/apps/{SALESFORCE_APP}/accounts/{connection}/sign-in", json={}, headers=admin)
    if started.status_code != 200:
        raise SystemExit(
            f"the stack could not start the Salesforce sign-in: {started.status_code} {started.text[:300]}"
        )
    back = sf["sign_in"]((data(started) or {}).get("authorizeUrl", ""), "kestrel.integration")
    done = gw.post(
        "/v1/sign-ins/complete", json={"state": back.get("state", ""), "code": back.get("code", "")}, headers=admin
    )
    if turned.status_code != 200 or done.status_code != 200:
        raise SystemExit(f"the stack could not sign the team in to Salesforce: {turned.text[:200]} {done.text[:200]}")


@dataclass
class Stack:
    accounts: Any
    gw: Any
    api: Any
    priya: dict[str, str]

    def token(self, email: str) -> str:
        """The token an assistant gets for the person through the company sign-in: the team MCP address refuses
        console tokens."""
        address = f"http://127.0.0.1:{TOOLS_PORT}/mcp/team_ops"
        return assistant_sign_in(self.accounts, email, address)["access_token"]


@contextmanager
def templates_stack(*, documents: bool = False, salesforce: dict[str, Any] | None = None) -> Generator[Stack]:
    """`salesforce` (a fake_salesforce.salesforce() yield) also loads the Salesforce plugin and points tools-service at
    that fake. `documents` also starts documents-service (beside kb-service and files-service) reading templates from
    tools-service, which `opsai resources` and the app's Resources tab join to the apps' copies."""
    paths = [str(p) for p in (STARTERS, SALESFORCE_PLUGIN if salesforce else None) if p and p.exists()]
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps(paths)} | (
        salesforce["settings"] if salesforce else {}
    )
    with (
        platform(env=PUBLIC) as (accounts, _),
        tools(
            {
                **AUTH,
                **PUBLIC,
                **plugins,
                "OPS_FLAGS": "mcp_gateway",
                "OPS_CONSOLE_URL": "https://console.kestrel.test",
                "OPS_AGENTS_URL": f"http://127.0.0.1:{AGENTS_PORT}",
            }
        ) as gw,
        ExitStack() as extra,
    ):
        tools_url = str(gw.base_url).rstrip("/")
        knowledge = (
            extra.enter_context(
                kb(Path(tempfile.mkdtemp(prefix="usecase-agents-")), documents_env={**AUTH, "OPS_TOOLS_URL": tools_url})
            )
            if documents
            else None
        )
        api = extra.enter_context(
            agents(
                gateway_url=tools_url,
                kb_url=str(knowledge.base_url).rstrip("/") if knowledge else None,
                env={**AUTH, **PUBLIC},
            )
        )
        priya = bearer(signed_in(accounts, "p.shah@harborpine.example"), "team_ops")
        gw.put(f"/v1/apps/{SOURCE}/team", json={"enabled": True}, headers=priya)
        yield Stack(accounts, gw, api, priya)
