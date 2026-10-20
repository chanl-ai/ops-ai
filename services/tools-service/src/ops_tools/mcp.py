"""A minimal MCP client over streamable HTTP: initialize, tools/list and tools/call, nothing else.

Each exchange is a JSON-RPC 2.0 POST to the server's URL. The server answers with one JSON body or with a server-sent
event stream carrying the response; both are read. The session id the server returns at initialize goes back on
every later request. There is no stdio transport: the gateway never starts a process. Every request goes through
the caller's client, which is the egress policy's, so an MCP server is reached only on a listed host at a checked
address.
"""

from __future__ import annotations

import json
from typing import Any, cast

import httpx

from .egress import for_tenant
from .modules.openapi import NAME, kebab, snake
from .modules.seed import fields_of

PROTOCOL_VERSION = "2025-06-18"
CLIENT = {"name": "ops-tools-service", "version": "0.1.0"}
SESSION = "Mcp-Session-Id"
# A server that pages its tool list past this is refused rather than followed forever.
MAX_PAGES = 20


# Every request to an MCP server waits at most this long.
TIMEOUT_MS = 15_000


class McpError(RuntimeError):
    """The server could not be reached, answered something that is not MCP, or returned a JSON-RPC error. `status` is
    the HTTP status when the server answered one of 400 or more, and `challenge` its `WWW-Authenticate` (a 401 names
    where its sign-in is described, c-331)."""

    def __init__(self, message: str, *, status: int | None = None, challenge: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.challenge = challenge


def _message(res: httpx.Response, request_id: int) -> dict[str, Any]:
    """The JSON-RPC response to `request_id`, from a JSON body or an event stream."""
    kind = res.headers.get("content-type", "")
    candidates: list[Any] = []
    if kind.startswith("text/event-stream"):
        for line in res.text.splitlines():
            if line.startswith("data:"):
                try:
                    candidates.append(json.loads(line[5:].strip()))
                except ValueError:
                    continue
    else:
        try:
            body: Any = res.json()
        except ValueError as e:
            raise McpError("The server's answer is not JSON.") from e
        candidates = cast(list[Any], body) if isinstance(body, list) else [body]
    for c in candidates:
        if isinstance(c, dict) and cast(dict[str, Any], c).get("id") == request_id:
            message = cast(dict[str, Any], c)
            if "error" in message:
                error: Any = message["error"]
                text = cast(dict[str, Any], error).get("message", "error") if isinstance(error, dict) else error
                raise McpError(f"The server refused the request: {text}")
            return message
    raise McpError("The server's answer carries no response to the request.")


class McpSession:
    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        tenant_id: str,
        headers: dict[str, str] | None = None,
        certificate: Any = None,
    ) -> None:
        """`tenant_id` is the tenant every request of the session is dialled for (egress `for_tenant`); `certificate` a
        connection's client certificate to present."""
        self.client = client
        self.url = url
        self.tenant_id = tenant_id
        self.certificate = certificate
        self.headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
        self.next_id = 0

    async def _post(self, method: str, params: dict[str, Any] | None, *, notify: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self.next_id += 1
            body["id"] = self.next_id
        try:
            res = await self.client.post(
                self.url,
                json=body,
                headers=self.headers,
                timeout=TIMEOUT_MS / 1000,
                extensions=for_tenant(self.tenant_id, self.certificate),
            )
        except httpx.HTTPError as e:
            raise McpError(f"The server could not be reached ({type(e).__name__}).") from e
        if notify:
            return {}
        if res.status_code >= 400:
            raise McpError(
                f"The server answered {res.status_code}.",
                status=res.status_code,
                challenge=res.headers.get("www-authenticate"),
            )
        if SESSION in res.headers:
            self.headers[SESSION] = res.headers[SESSION]
        result: Any = _message(res, self.next_id).get("result")
        return cast(dict[str, Any], result) if isinstance(result, dict) else {}

    async def initialize(self) -> dict[str, Any]:
        params = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT}
        result = await self._post("initialize", params)
        await self._post("notifications/initialized", None, notify=True)
        return result

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await self._post("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(
                cast(dict[str, Any], t) for t in cast(list[Any], page.get("tools") or []) if isinstance(t, dict)
            )
            cursor = page.get("nextCursor")
            if not cursor:
                return tools
        raise McpError(f"The server's tool list runs past {MAX_PAGES} pages.")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self._post("tools/call", {"name": name, "arguments": arguments})


def tool_output(result: dict[str, Any]) -> tuple[bool, Any]:
    """(ok, output) from a tools/call result: structured content when the server gives it, else its text."""
    if result.get("structuredContent") is not None:
        output: Any = result["structuredContent"]
    else:
        parts = [
            str(cast(dict[str, Any], c).get("text", ""))
            for c in cast(list[Any], result.get("content") or [])
            if isinstance(c, dict) and cast(dict[str, Any], c).get("type") == "text"
        ]
        output = {"text": "\n".join(parts)}
    return not result.get("isError"), output


def discovered(tools: list[dict[str, Any]], url: str, server: dict[str, Any]) -> dict[str, Any]:
    """The console's DiscoveryResult for an MCP server's tools. A tool's operation name is its name in snake case;
    the server's own name is kept as the operation's `path`, which the mcp executor calls. Every tool is
    discovered as a write, as OpenAPI operations are."""
    info: dict[str, Any] = server.get("serverInfo") or {}
    title = str(info.get("title") or info.get("name") or httpx.URL(url).host)
    warnings: list[str] = []
    operations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for t in tools:
        original = str(t.get("name", ""))
        name = snake(original)
        if not NAME.match(name) or name in seen:
            warnings.append(f"{original or 'A tool'} was skipped: no usable unique name.")
            continue
        seen.add(name)
        schema: Any = t.get("inputSchema") or {}
        operations.append(
            {
                "name": name,
                "description": str(t.get("description") or name),
                "access": "write",
                "method": None,
                "path": original,
                "group": "tools",
                "input": fields_of(cast(dict[str, Any], schema) if isinstance(schema, dict) else {}),
                "headers": [],
            }
        )
    return {
        "type": "mcp",
        "system": title,
        "suggestedName": kebab(title),
        "version": str(info.get("version") or "1.0.0"),
        "endpoint": url,
        "operations": operations,
        "warnings": warnings,
    }
