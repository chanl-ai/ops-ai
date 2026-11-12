"""The MCP adapter: an outside assistant (Claude Code, Cursor) lists and runs a team's tools at
`/mcp/{team}` over streamable HTTP, through the same `GatewayCalls.call` as POST /v1/calls.

The adapter only translates. It resolves the caller from the Bearer key or token with ops_identity, checks the URL's
team is the caller's and that the caller holds `tools:run` there, and hands the request to the official SDK's
stateless server; tools/list reads the registry and tools/call is one gateway call. Nothing is decided or executed
here: the registry, the schema, OPA, the rate window, the executor and the call log are the gateway's.

Beside the team's tools it offers public API operations as tools (mcp_tools.py: list and install templates), each
called on its service with the assistant's own credential.

Slice 1 lists the team's read operations only. Every call is a test run, so it uses an app's sandbox account when the
team has one, and a write called by name reaches the gateway, which refuses it without a person's approval.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from ops_access import can
from ops_identity import Auth, Principal
from ops_service_kit.errors import ApiError, NotFound, ServiceUnavailable
from ops_service_kit.http import error_body
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from ops_store import isolation

from .environments import TEST
from .gateway_calls import MCP, WRITES, Allowed, CallRequest, GatewayCalls
from .mcp_tools import PlatformTools
from .modules.directory import Directory, Team
from .registry import ToolRegistry
from .store.modules import Aggregate

_PATH = re.compile(r"^(?:/mcp)?/(?P<team>[^/]+)/?$")
_CLIENT_INFO = "io.modelcontextprotocol/clientInfo"


@dataclass(frozen=True)
class McpCaller:
    """Who an MCP request is for, resolved before the SDK sees it and read back by the handlers from the ASGI scope."""

    principal: Principal
    team: Team
    # The request's own Authorization header, which a platform tool sends on so the service decides as for this person.
    authorization: str


class McpAdapter:
    def __init__(
        self,
        *,
        calls: GatewayCalls,
        registry: ToolRegistry,
        directory: Directory,
        auth: Auth,
        platform: PlatformTools | None = None,
    ) -> None:
        self.calls = calls
        self.platform = platform or PlatformTools({"agents": Settings().agents_url or ""})
        self.registry = registry
        self.directory = directory
        self.auth = auth
        self.server: Server[Any] = Server(
            "ops-ai-tools",
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
            on_list_prompts=self._list_prompts,
            on_get_prompt=self._get_prompt,
        )
        self.manager: StreamableHTTPSessionManager | None = None

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[None]:
        """Entered in the gateway's lifespan. The SDK's manager runs once, so each lifespan gets its own."""
        # Stateless with JSON answers: each POST stands alone, so any replica answers it and nothing is kept per client.
        manager = StreamableHTTPSessionManager(app=self.server, stateless=True, json_response=True)
        async with manager.run():
            self.manager = manager
            try:
                yield
            finally:
                self.manager = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        found = _PATH.match(scope["path"])
        try:
            if found is None:
                raise NotFound("No MCP server answers at this URL; use /mcp/{team}.")
            team_id = found["team"]
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            # 401 without a credential, 403 team_forbidden when the key or token belongs to another team.
            principal = await self.auth.identity.bearer(headers.get("authorization"), team_id)
            can(principal, "tools", "run", team=team_id, what="this team's tools")
        except ApiError as e:
            await _refuse(send, e)
            return
        # An id the seed does not know is nobody's team, so it sees no module (never the all-scope fallback).
        team = self.directory.team_by_id(team_id) or Team(team_id, team_id, (), "owned")
        authorization = headers.get("authorization") or ""
        scope.setdefault("state", {})["mcp_caller"] = McpCaller(principal, team, authorization)
        # The team scope an API route gets from its auth dependency. This adapter is an ASGI app, so nothing else enters
        # it, and the registry and connection store raise NoTenantError without it. The SDK starts each request's
        # handler task from this task's context, so the scope reaches tools/list and tools/call.
        isolation.enter_caller(principal, dev=self.auth.identity.dev_user is not None)
        if self.manager is None:
            await _refuse(send, ServiceUnavailable("The MCP server is starting or stopping."))
            return
        await self.manager.handle_request(scope, receive, send)

    def _sees(self, team: Team) -> Any:
        def sees(module: Aggregate) -> bool:
            return self.directory.sees_module(team, module)

        return sees

    async def _list_tools(self, ctx: Any, _params: Any) -> types.ListToolsResult:
        who = _caller(ctx)
        rows = await self.registry.grantable(who.principal.tenant_id, self._sees(who.team))
        tools = [
            types.Tool(
                name=r["name"],
                description=r["description"],
                input_schema=r["input_schema"],
                annotations=types.ToolAnnotations(title=r["name"], read_only_hint=True, open_world_hint=True),
            )
            for r in rows
            if r["access"] not in WRITES
        ]
        return types.ListToolsResult(tools=[*self.platform.tools(), *tools])

    async def _list_prompts(self, ctx: Any, _params: Any) -> types.ListPromptsResult:
        """The team's skills as prompts, read from agents-service as the caller, so a person sees what they may read."""
        who = _caller(ctx)
        return types.ListPromptsResult(
            prompts=await self.platform.prompts(authorization=who.authorization, team=who.team.id)
        )

    async def _get_prompt(self, ctx: Any, params: Any) -> types.GetPromptResult:
        who = _caller(ctx)
        args = {str(k): str(v) for k, v in dict(params.arguments or {}).items()}
        found = await self.platform.prompt(str(params.name), args, authorization=who.authorization, team=who.team.id)
        if found is None:
            raise ValueError(f"No skill named {params.name} in this team.")
        return found

    async def _call_tool(self, ctx: Any, params: Any) -> types.CallToolResult:
        who = _caller(ctx)
        if self.platform.offers(str(params.name)):
            return await self.platform.call(
                str(params.name), dict(params.arguments or {}), authorization=who.authorization, team=who.team.id
            )
        request = CallRequest(
            tool=str(params.name),
            input=dict(params.arguments or {}),
            # Every MCP call is its own: a read is not deduplicated, and a write never runs here without a person.
            key=new_id("mcp"),
            # A test run: it takes the app's sandbox account when the team has one, and its writes wait for a person.
            run_context={"environment": TEST},
        )
        outcome = await self.calls.call(
            who.principal, request, channel=MCP, client_name=_client_name(ctx), sees=self._sees(who.team)
        )
        if isinstance(outcome, Allowed):
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(outcome.output, default=str))],
                structured_content=_structured(outcome.output) | {"callId": outcome.call_id},
                is_error=not outcome.ok,
            )
        reason = "; ".join(outcome.reasons)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"{outcome.code}: {reason}")],
            structured_content={"callId": outcome.call_id, "code": outcome.code, "reasons": outcome.reasons},
            is_error=True,
        )


def _caller(ctx: Any) -> McpCaller:
    return cast(McpCaller, ctx.request.scope["state"]["mcp_caller"])


def _client_name(ctx: Any) -> str | None:
    """The assistant's own name: the 2026 protocol stamps clientInfo on every request; an older client sent it only in
    its initialize, which a stateless server does not keep, so its User-Agent stands in."""
    meta = cast(dict[str, Any], ctx.meta or {})
    info = meta.get(_CLIENT_INFO)
    if isinstance(info, dict) and (name := cast(dict[str, Any], info).get("name")):
        return str(name)[:120]
    agent = ctx.request.headers.get("user-agent") if ctx.request is not None else None
    return str(agent)[:120] if agent else None


def _structured(output: Any) -> dict[str, Any]:
    """structuredContent must be an object; a list or a scalar answer is wrapped."""
    return dict(cast(dict[str, Any], output)) if isinstance(output, dict) else {"result": output}


async def _refuse(send: Send, e: ApiError) -> None:
    body = error_body(e.status, e.code, e.message)
    headers = [(b"content-type", b"application/json")]
    if e.status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="ops-ai-tools"'))
    await send({"type": "http.response.start", "status": e.status, "headers": headers})
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})
