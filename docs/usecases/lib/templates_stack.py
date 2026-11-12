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

PACK = "opsai.starters"
SOURCE = f"plugin:{PACK}"
# A starter skill from the starters pack, with inputs (topic, doc_type).
SKILL = "doc-coauthoring"
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
def templates_stack(*, documents: bool = False) -> Generator[Stack]:
    """`documents` also starts documents-service (beside kb-service and files-service) reading templates from
    tools-service, which `opsai resources` and the app's Resources tab join to the apps' copies."""
    plugins = {"OPS_PLUGINS": "true", "OPS_PLUGIN_PATHS": json.dumps([str(STARTERS)] if STARTERS.exists() else [])}
    with (
        platform(env=PUBLIC) as (accounts, _),
        tools(
            {
                **AUTH,
                **PUBLIC,
                **plugins,
                "OPS_FLAGS": "mcp_gateway",
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
