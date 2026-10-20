"""A fake bank API the HTTP executor calls in tests, in process: it records every request it receives, so a test can
show that a refused call never left the gateway."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from .fake_mcp import mount_mcp, tools

SPEC = json.loads((Path(__file__).parent / "fixtures" / "openapi_bank.json").read_text())

HOST = "bank.test"
ENDPOINT = f"https://{HOST}/v1"
# How long /v1/slow takes to answer. In process (ASGITransport) httpx enforces no timeout, so SlowAware stands in for
# the network: it times the request out when the caller's read timeout is shorter than this.
SLOW_S = 5.0


class SlowAware(httpx.AsyncBaseTransport):
    """Passes requests to the fake bank, except /v1/slow, which answers only to a caller willing to wait SLOW_S."""

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self.inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/slow":
            limit = cast(dict[str, float | None], request.extensions.get("timeout") or {}).get("read")
            if limit is not None and limit < SLOW_S:
                raise httpx.ReadTimeout("no answer within the read timeout", request=request)
            return httpx.Response(200, json={"slow": True})
        return await self.inner.handle_async_request(request)


def fake_bank(mcp_tools: list[dict[str, Any]] | None = None) -> tuple[FastAPI, list[dict[str, Any]]]:
    """`mcp_tools` is the fake MCP server's tool list at /v1/mcp; a test changes it in place to show drift."""
    app = FastAPI()
    received: list[dict[str, Any]] = []
    mount_mcp(app, mcp_tools if mcp_tools is not None else tools())

    @app.middleware("http")
    async def record(request: Request, call_next: Any) -> Any:  # pyright: ignore[reportUnusedFunction]
        body = await request.body()
        received.append(
            {
                "method": request.method,
                "path": request.url.path,
                "query": str(request.url.query),
                "body": body,
                "headers": dict(request.headers),
            }
        )
        return await call_next(request)

    @app.get("/v1/accounts/{account_id}")
    async def account(account_id: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return {"accountId": account_id, "balance": 1200.5, "holder": {"name": "Marcus Webb", "sin": "123-456-789"}}

    @app.post("/v1/holds")
    async def hold(request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "held", "request": await request.json()}

    @app.get("/v1/openapi.json")
    async def spec() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return SPEC

    @app.get("/v1/not-a-spec")
    async def not_a_spec() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse("<html>login</html>")

    @app.get("/v1/echo-headers")
    async def echo_headers(request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """A careless upstream that repeats the request's headers in its answer."""
        return {"headers": dict(request.headers)}

    @app.get("/v1/echo-key-reversed")
    async def echo_key_reversed(request: Request) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """An upstream that answers with the key it was sent, reversed: a scrub of the literal value lets it through,
        and a transform can turn it back."""
        return {"k": request.headers.get("x-api-key", "")[::-1]}

    @app.get("/v1/echo-url/{account_id}")
    async def echo_url(request: Request, account_id: str) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """A careless upstream that repeats the URL it was called on, query and all."""
        return {"accountId": account_id, "url": str(request.url), "query": dict(request.query_params)}

    @app.get("/v1/limited")
    async def limited() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse({"error": "slow down"}, status_code=429)

    @app.get("/v1/broken")
    async def broken() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse({"error": "boom"}, status_code=500)

    return app, received
