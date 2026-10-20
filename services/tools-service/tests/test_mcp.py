"""Discovery, import and calls through an MCP server over streamable HTTP, against the fake server on the fake bank.
One test per way an MCP tool could be reached off the allow-list, run as a read unconfirmed, or keep running after
the server stopped listing it."""

from __future__ import annotations

from typing import Any

from .conftest import Api, Bank
from .fake_upstream import ENDPOINT, HOST

MCP_URL = f"{ENDPOINT}/mcp"
SOURCE = {"kind": "mcp", "url": MCP_URL}


def _op(name: str, access: str) -> dict[str, Any]:
    return {"name": name, "description": "", "access": access, "group": "tools", "input": []}


async def _listed(api: Api) -> None:
    await api.client.post("/v1/egress/hosts", json={"value": HOST})


async def test_discovery_lists_the_servers_tools_as_writes(bank_api: Api) -> None:
    await _listed(bank_api)
    r = await bank_api.call("POST", "/discover", json=SOURCE)
    assert r.status_code == 200, r.text
    found = r.json()["data"]
    assert (found["type"], found["system"], found["version"]) == ("mcp", "Case desk", "4.1.0")
    assert {o["name"]: o["access"] for o in found["operations"]} == {"lookup_case": "write", "close_case": "write"}
    assert found["operations"][0]["input"] == [{"name": "caseId", "type": "string", "required": True}]


async def test_an_mcp_server_off_the_allow_list_is_never_contacted(bank_api: Api, received: list[Any]) -> None:
    r = await bank_api.call("POST", "/discover", json=SOURCE)
    assert r.status_code == 400 and r.json()["error"]["code"] == "egress_denied"
    assert not received


async def test_an_imported_tool_runs_through_tools_call(bank_api: Api, gateway_call: Any) -> None:
    await _listed(bank_api)
    body = {"source": SOURCE, "operations": [_op("lookup_case", "read")]}
    r = await bank_api.call("POST", "/mod_document_service/operations/import", json=body)
    assert r.status_code == 200, r.text
    res = await gateway_call("lookup_case", {"caseId": "CASE-4112"})
    assert res.status_code == 200, res.text
    assert res.json()["data"]["output"] == {"tool": "lookupCase", "arguments": {"caseId": "CASE-4112"}}


async def test_a_tool_the_server_stops_listing_drifts_the_module_and_stops_its_calls(
    bank: Bank, gateway_call: Any
) -> None:
    await _listed(bank.api)
    first = {"source": SOURCE, "operations": [_op("lookup_case", "read")]}
    r = await bank.api.call("POST", "/mod_document_service/operations/import", json=first)
    assert r.json()["data"]["drift"] is False
    # The server renames lookupCase: the reviewed tool is gone and an unreviewed one stands in its place.
    bank.mcp_tools[0] = {**bank.mcp_tools[0], "name": "findCase"}
    again = {"source": SOURCE, "operations": [_op("find_case", "read")]}
    r = await bank.api.call("POST", "/mod_document_service/operations/import", json=again)
    assert r.status_code == 200, r.text
    assert r.json()["data"]["drift"] is True
    assert r.json()["data"]["approvalState"] in ("draft", "needs_approval")
    res = await gateway_call("find_case", {"caseId": "CASE-4112"})
    assert res.status_code == 403 and res.json()["error"]["code"] == "module_drifted"


async def test_a_server_refusing_a_request_is_a_bad_gateway(bank: Bank) -> None:
    await _listed(bank.api)
    r = await bank.api.call("POST", "/discover", json={"kind": "mcp", "url": f"{ENDPOINT}/openapi.json"})
    assert r.status_code == 502, r.text
