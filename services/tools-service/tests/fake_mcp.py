"""A fake MCP server over streamable HTTP, mounted on the fake bank at /v1/mcp. It answers initialize and tools/list
with JSON and tools/call with an event stream, insists on the session id it issued, and lets a test change its tool
list to show drift."""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

SESSION = "sess-fake-1"


def tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "lookupCase",
            "description": "A case by its id",
            "inputSchema": {"type": "object", "properties": {"caseId": {"type": "string"}}, "required": ["caseId"]},
        },
        {
            "name": "closeCase",
            "description": "Close a case",
            "inputSchema": {"type": "object", "properties": {"caseId": {"type": "string"}}, "required": ["caseId"]},
        },
    ]


def mount_mcp(app: FastAPI, listed: list[dict[str, Any]]) -> None:
    @app.post("/v1/mcp")
    async def mcp(request: Request) -> Response:  # pyright: ignore[reportUnusedFunction]
        body: dict[str, Any] = await request.json()
        method, rid = body.get("method"), body.get("id")
        if method == "notifications/initialized":
            return Response(status_code=202)
        if method != "initialize" and request.headers.get("mcp-session-id") != SESSION:
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": "no session"}})
        if method == "initialize":
            result: dict[str, Any] = {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "Case desk", "version": "4.1.0"},
            }
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": result}, headers={"Mcp-Session-Id": SESSION})
        if method == "tools/list":
            return JSONResponse({"jsonrpc": "2.0", "id": rid, "result": {"tools": listed}})
        if method == "tools/call":
            params: dict[str, Any] = body.get("params") or {}
            called: dict[str, Any] = {
                "content": [{"type": "text", "text": f"{params.get('name')} done"}],
                "structuredContent": {"tool": params.get("name"), "arguments": params.get("arguments")},
            }
            stream = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': called})}\n\n"
            return Response(stream, media_type="text/event-stream")
        return JSONResponse({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
