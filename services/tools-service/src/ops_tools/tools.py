"""The tools behind the gateway. Until Protobox's tool servers exist these are the Runtime's local demo tools, now
run here after the gateway has allowed the call instead of inside the Runtime."""

from __future__ import annotations

from typing import Any, Protocol

from ops_agent_kernel.ports import ToolOutcome
from ops_agents.activities.catalog import Catalog
from ops_agents.activities.tools import LocalReplySender, LocalToolExecutor

# The local executor refuses a write without a token. By the time a call reaches it the gateway has decided, so
# this marker only says so; the token itself was checked by OPA.
DECIDED = "gateway-allowed"


class ToolRunner(Protocol):
    async def run(self, tool: str, arguments: dict[str, Any], *, key: str) -> ToolOutcome: ...


class LocalToolRunner:
    def __init__(self, catalog: Catalog, replies: LocalReplySender | None = None) -> None:
        self.tools = LocalToolExecutor(catalog)
        self.replies = replies or LocalReplySender()

    async def run(self, tool: str, arguments: dict[str, Any], *, key: str) -> ToolOutcome:
        if tool == "send_reply":
            reference = await self.replies.send(
                key=key, to=arguments["to"], subject=arguments["subject"], body=arguments["body"]
            )
            return ToolOutcome(True, {"status": "sent", "reference": reference})
        return await self.tools.execute(tool, arguments, key=key, approval_token=DECIDED)
