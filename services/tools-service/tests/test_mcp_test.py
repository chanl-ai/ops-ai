"""How Test reads an MCP server's answer to tools/list, by failure mode: a server that answers 200 with a JSON-RPC
error (no session, an unknown method) would read as working; a streamed answer would read as not JSON-RPC; and an
app whose address is not the token's resource is not an MCP server, so it keeps its test address."""

from __future__ import annotations

import httpx

from ops_tools.connections.service import is_mcp_server, mcp_error


def _answer(body: str, kind: str = "application/json") -> httpx.Response:
    return httpx.Response(200, text=body, headers={"content-type": kind})


def test_a_json_rpc_error_in_a_200_is_a_refusal_with_its_message() -> None:
    said = mcp_error(_answer('{"jsonrpc":"2.0","id":1,"error":{"code":-32600,"message":"no session"}}'))
    assert said == "no session"
    assert mcp_error(_answer('{"jsonrpc":"2.0","id":1,"result":{"tools":[]}}')) is None


def test_a_streamed_answer_is_read_from_its_first_data_line() -> None:
    streamed = 'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n'
    assert mcp_error(_answer(streamed, "text/event-stream")) is None
    assert mcp_error(_answer("<html>sign in</html>")) == "its answer was not JSON-RPC"


def test_only_an_address_that_is_its_own_resource_is_an_mcp_server() -> None:
    assert is_mcp_server({"baseUrl": "https://api.bank.test/mcp/x", "resource": "https://api.bank.test/mcp/x/"})
    assert not is_mcp_server({"baseUrl": "https://api.bank.test", "resource": "https://api.bank.test/v1"})
    assert not is_mcp_server({"baseUrl": "https://api.bank.test"})
