"""The tool step's timeout port (c-332): with `onTimeout: port`, a gateway answer that the system did not answer in
time leaves by `timeout`; any other failure, or a step that does not ask, leaves by `error` as before."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from ops_engine.compiler import NodeCall, gateway_call
from ops_engine.node_types import BASIC_TYPES
from ops_engine.ports import ToolResult

TOOL = next(t for t in BASIC_TYPES if t.id == "ops.action.tool")


class AnsweringTools:
    def __init__(self, result: ToolResult) -> None:
        self.result = result

    async def call(
        self, operation: str, input: dict[str, Any], key: str, generation: int | None, token: str | None
    ) -> ToolResult:
        return self.result


async def _port(code: str, params: dict[str, Any]) -> str:
    failed = ToolResult(False, {"error": {"code": code, "side": "upstream"}}, reason="the operation returned an error")
    call = SimpleNamespace(
        params={"operation": "get_account", **params},
        ports=SimpleNamespace(tools=AnsweringTools(failed)),
        key="r1:lookup:1:1",
        generation=1,
        run_id="r1",
        scope={},
    )
    return (await gateway_call(cast(NodeCall, call))).port


def test_the_port_exists_only_when_the_step_asks() -> None:
    assert "timeout" in TOOL.output_ports({"operation": "x", "onTimeout": "port"})
    assert "timeout" not in TOOL.output_ports({"operation": "x"})


@pytest.mark.parametrize(
    ("code", "params", "port"),
    [
        ("UPSTREAM_TIMEOUT", {"onTimeout": "port"}, "timeout"),
        ("CONNECT_TIMEOUT", {"onTimeout": "port"}, "timeout"),
        ("UPSTREAM_ERROR", {"onTimeout": "port"}, "error"),
        ("UPSTREAM_TIMEOUT", {}, "error"),
    ],
)
async def test_a_timeout_leaves_by_its_own_port_only_when_asked(code: str, params: dict[str, Any], port: str) -> None:
    assert await _port(code, params) == port
