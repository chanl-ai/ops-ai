"""An MCP request carries its caller's team into the handlers, as an API route's dependency does. The shared suite
fixture sets a tenant-wide context around every test, which would hide a missing one, so the call runs in a task that
starts from an empty context, as a deployed server's request does."""

from __future__ import annotations

import asyncio
import contextvars
from collections.abc import Coroutine
from typing import Any

from .test_mcp_server import Stack, stack  # noqa: F401  (the fixture)


def _in_empty_context[T](coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
    return asyncio.get_running_loop().create_task(coro, context=contextvars.Context())


async def test_a_read_over_mcp_runs_in_the_callers_team_with_no_ambient_scope(stack: Stack) -> None:  # noqa: F811
    async def go() -> tuple[list[str], bool | None, object]:
        async with stack.running(), stack.http("ok_lending") as http, stack.client(http, "/mcp/team_lending") as c:
            names = [t.name for t in (await c.list_tools()).tools]
            result = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
        return names, result.is_error, result.structured_content

    names, is_error, structured = await _in_empty_context(go())
    assert "lookup_case" in names
    assert is_error is False, structured
