"""The MCP adapter: an outside assistant (Claude Code, Cursor) lists and runs a team's tools at
`/mcp/{team}` over streamable HTTP, through the same `GatewayCalls.call` as POST /v1/calls.

The adapter only translates. It resolves the caller from the Bearer key or token with ops_identity, checks the URL's
team is the caller's, and hands the request to the official SDK's
stateless server; tools/list reads the registry and tools/call is one gateway call. Nothing is decided or executed
here: the registry, the schema, OPA, the rate window, the executor and the call log are the gateway's.

Beside the team's tools it offers public API operations as tools (mcp_tools.py: list and install templates) and the
team's skills as prompts. Each is one gateway call too, so it has its call log row and rate window and a write waits
as any MCP write does; the operation itself calls its service with a service token carrying the person's own rights.

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

import httpx
import mcp_types as types
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.types import Receive, Scope, Send

from ops_access import can
from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ActingForTokens, Auth, Principal, ServiceClient, service_signer
from ops_service_kit.errors import ApiError, NotFound, ServiceUnavailable
from ops_service_kit.http import error_body
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from ops_store import isolation

from .environments import TEST
from .gateway_calls import MCP, WRITES, Allowed, CallRequest, GatewayCalls, Outcome, Run
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


class McpAdapter:
    def __init__(
        self,
        *,
        calls: GatewayCalls,
        registry: ToolRegistry,
        directory: Directory,
        auth: Auth,
        platform: PlatformTools | None = None,
        public_url: str | None = None,
        issuer_url: str | None = None,
    ) -> None:
        # This service's public base (OPS_TOOLS_PUBLIC_URL): an assistant's token is for `<public_url>/mcp/<team>` and
        # nothing else. platform-service at its own public base (OPS_PLATFORM_PUBLIC_URL) is the authorization server.
        # Behind a proxy the two differ (/api/tools, /api/platform). Without both, only API keys open an MCP address.
        self.public_url = public_url.rstrip("/") if public_url and issuer_url else None
        self.issuer_url = issuer_url.rstrip("/") if public_url and issuer_url else None
        self.calls = calls
        self.platform = platform or _platform_tools(Settings())
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
            authorization = headers.get("authorization")
            if self.public_url is None and not (authorization or "").startswith("Bearer ok_"):
                raise ServiceUnavailable(
                    "This install names no public address for its MCP service or its sign-in issuer "
                    "(OPS_TOOLS_PUBLIC_URL, OPS_PLATFORM_PUBLIC_URL), so assistants cannot sign in. "
                    "API keys still work."
                )
            # 401 without a credential, 403 team_forbidden when the key or token belongs to another team. Any member
            # opens a session and lists; each call checks its own right and a refusal is a tool error.
            principal = await self.auth.identity.bearer(
                authorization, team_id, resource=f"{self.public_url}/mcp/{team_id}" if self.public_url else None
            )
        except ApiError as e:
            await _refuse(send, e, self._metadata_url(scope))
            return
        # An id the seed does not know is nobody's team, so it sees no module (never the all-scope fallback).
        team = self.directory.team_by_id(team_id) or Team(team_id, team_id, (), "owned")
        scope.setdefault("state", {})["mcp_caller"] = McpCaller(principal, team)
        # The team scope an API route gets from its auth dependency. This adapter is an ASGI app, so nothing else enters
        # it, and the registry and connection store raise NoTenantError without it. The SDK starts each request's
        # handler task from this task's context, so the scope reaches tools/list and tools/call.
        isolation.enter_caller(principal, dev=self.auth.identity.dev_user is not None)
        if self.manager is None:
            await _refuse(send, ServiceUnavailable("The MCP server is starting or stopping."))
            return
        await self.manager.handle_request(scope, receive, send)

    def _metadata_url(self, scope: Scope) -> str | None:
        found = _PATH.match(scope["path"])
        if self.public_url is None or found is None:
            return None
        return f"{self.public_url}/.well-known/oauth-protected-resource/mcp/{found['team']}"

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

    async def _platform_call(self, ctx: Any, name: str, args: dict[str, Any], run: Run) -> Outcome:
        """One platform operation as a gateway call for the caller: logged on the MCP channel, rate limited, and a write
        held as the team's rule for MCP writes says."""
        who = _caller(ctx)
        request = CallRequest(tool=name, input=args, key=new_id("mcp"), run_context={"environment": TEST})
        return await self.calls.call(
            who.principal,
            request,
            channel=MCP,
            client_name=None if who.principal.client_id else _client_name(ctx),
            operation=(self.platform.resolved(name), run),
        )

    async def _list_prompts(self, ctx: Any, _params: Any) -> types.ListPromptsResult:
        """The team's skills as prompts, read from agents-service as the caller, so a person sees what they may read;
        none when they may read no skills."""
        who = _caller(ctx)

        async def run(_args: dict[str, Any]) -> ToolOutcome:
            return await self.platform.prompts(who=who.principal, team=who.team.id)

        out = await self._platform_call(ctx, "prompts/list", {}, run)
        output: Any = out.output if isinstance(out, Allowed) and out.ok else {}
        found = cast(list[Any], cast(dict[str, Any], output).get("prompts") or [])
        return types.ListPromptsResult(prompts=[types.Prompt.model_validate(p) for p in found])

    async def _get_prompt(self, ctx: Any, params: Any) -> types.GetPromptResult:
        who = _caller(ctx)
        args = {str(k): str(v) for k, v in dict(params.arguments or {}).items()}

        async def run(_args: dict[str, Any]) -> ToolOutcome:
            return await self.platform.prompt(str(params.name), args, who=who.principal, team=who.team.id)

        out = await self._platform_call(ctx, "prompts/get", {"name": str(params.name), "arguments": args}, run)
        if isinstance(out, Allowed) and out.ok:
            return types.GetPromptResult.model_validate(out.output)
        # The protocol has no error result for a prompt, so a refusal or a missing skill is its error message.
        raise ValueError(_said(out))

    async def _call_tool(self, ctx: Any, params: Any) -> types.CallToolResult:
        who = _caller(ctx)
        # Any member opens a session and lists; running any tool, a platform one included, needs tools:run.
        try:
            can(who.principal, "tools", "run", team=who.team.id, what="this team's tools")
        except ApiError as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"{e.code}: {e.message}")],
                structured_content={"code": e.code, "status": e.status, "message": e.message},
                is_error=True,
            )
        if self.platform.offers(name := str(params.name)):
            args = dict(params.arguments or {})

            async def run(given: dict[str, Any]) -> ToolOutcome:
                return await self.platform.run(name, given, who=who.principal, team=who.team.id)

            return _tool_result(await self._platform_call(ctx, name, args, run))
        request = CallRequest(
            tool=str(params.name),
            input=dict(params.arguments or {}),
            # Every MCP call is its own: a read is not deduplicated, and a write never runs here without a person.
            key=new_id("mcp"),
            # A test run: it takes the app's sandbox account when the team has one, and its writes wait for a person.
            run_context={"environment": TEST},
        )
        outcome = await self.calls.call(
            who.principal,
            request,
            channel=MCP,
            # A signed-in assistant is named by its client id; what it says about itself is not kept beside it.
            client_name=None if who.principal.client_id else _client_name(ctx),
            sees=self._sees(who.team),
        )
        return _tool_result(outcome)


def _said(outcome: Outcome) -> str:
    """What a refused or failed call tells the assistant: its code and reason."""
    if isinstance(outcome, Allowed):
        output: Any = outcome.output
        err: Any = cast(dict[str, Any], output).get("error") if isinstance(output, dict) else None
        e = cast(dict[str, Any], err) if isinstance(err, dict) else {}
        return f"{e.get('code') or 'error'}: {e.get('message') or 'the call failed'}"
    return f"{outcome.code}: {'; '.join(outcome.reasons)}"


def _tool_result(outcome: Outcome) -> types.CallToolResult:
    """A gateway outcome as an MCP tool result: a refusal or a failure is a tool error, never a protocol error."""
    if isinstance(outcome, Allowed):
        text = json.dumps(outcome.output, default=str) if outcome.ok else _said(outcome)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)],
            structured_content=_structured(outcome.output) | {"callId": outcome.call_id},
            is_error=not outcome.ok,
        )
    reason = "; ".join(outcome.reasons)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=f"{outcome.code}: {reason}")],
        structured_content={"callId": outcome.call_id, "code": outcome.code, "reasons": outcome.reasons},
        is_error=True,
    )


def _platform_tools(settings: Settings) -> PlatformTools:
    """The platform operations, signed with this service's key; with no key (outside dev, unset) none are offered."""
    try:
        signer = service_signer(settings)
    except ValueError:
        signer = None
    return PlatformTools({"agents": settings.agents_url or ""}, signer, people=_acting_for(settings, signer))


def _acting_for(settings: Settings, signer: Any) -> ActingForTokens | None:
    """Whom an operation that makes a record acts for, as agents-service's tool calls name theirs
    (ops_agents.api.acting_for): minted by platform-service on a platform stack, self-signed in dev."""
    if signer is None:
        return None
    if settings.auth_mode != "platform":
        return ActingForTokens.for_dev(signer, service="tools", audience="agents")
    internal = settings.platform_internal_url or f"http://127.0.0.1:{settings.platform_internal_port}"
    platform = httpx.AsyncClient(base_url=internal, timeout=10)
    return ActingForTokens.from_platform(
        ServiceClient.for_settings(settings, platform, service="tools", audience="platform")
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


async def _refuse(send: Send, e: ApiError, metadata_url: str | None = None) -> None:
    body = error_body(e.status, e.code, e.message)
    headers = [(b"content-type", b"application/json")]
    if e.status == 401:
        challenge = 'Bearer realm="ops-ai-tools"' + (f', resource_metadata="{metadata_url}"' if metadata_url else "")
        headers.append((b"www-authenticate", challenge.encode()))
    await send({"type": "http.response.start", "status": e.status, "headers": headers})
    await send({"type": "http.response.body", "body": json.dumps(body).encode()})
