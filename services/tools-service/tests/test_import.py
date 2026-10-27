"""Discovery and import from an OpenAPI document, served by the in-process fake bank. One test per way an import
could reach an unchecked host, take a write for a read, or run something the document does not describe."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_tools.store.modules import ModuleStore

from .conftest import Api
from .fake_upstream import ENDPOINT, HOST

SPEC_URL = f"{ENDPOINT}/openapi.json"
SOURCE = {"kind": "openapi", "specUrl": SPEC_URL}


async def _listed(api: Api) -> None:
    r = await api.client.post("/v1/egress/hosts", json={"value": HOST})
    assert r.status_code in (200, 201), r.text


async def test_discovery_maps_the_document_and_presets_access_from_the_method(bank_api: Api) -> None:
    await _listed(bank_api)
    r = await bank_api.call("POST", "/discover", json=SOURCE)
    assert r.status_code == 200, r.text
    found = r.json()["data"]
    assert (found["system"], found["version"], found["endpoint"]) == ("Statements API", "2.3.0", ENDPOINT)
    ops = {o["name"]: o for o in found["operations"]}
    assert set(ops) == {"get_account", "place_hold", "get_statements"}
    assert {n: o["access"] for n, o in ops.items()} == {
        "get_account": "read",
        "place_hold": "write",
        "get_statements": "read",
    }
    assert found["noAuth"] is False, "the document declares an API key scheme"
    assert [f["name"] for f in ops["place_hold"]["input"]] == ["accountId", "hours", "reason"]
    assert ops["get_statements"]["input"][0] == {"name": "month", "type": "string", "required": True, "format": "date"}
    assert any("upload_file" in w for w in found["warnings"])
    assert all("headers" not in o for o in found["operations"]), "secret references stay on the service"


async def test_a_document_on_an_unlisted_host_or_over_http_is_never_fetched(bank_api: Api, received: list[Any]) -> None:
    r = await bank_api.call("POST", "/discover", json=SOURCE)
    assert r.status_code == 400 and r.json()["error"]["code"] == "egress_denied"
    await _listed(bank_api)
    r = await bank_api.call("POST", "/discover", json={"kind": "openapi", "specUrl": f"http://{HOST}/v1/openapi.json"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "egress_denied"
    assert not received


async def test_a_page_that_is_not_a_document_is_refused(bank_api: Api) -> None:
    await _listed(bank_api)
    r = await bank_api.call("POST", "/discover", json={"kind": "openapi", "specUrl": f"{ENDPOINT}/not-a-spec"})
    assert r.status_code == 400
    r = await bank_api.call("POST", "/discover", json={"kind": "openapi", "specUrl": f"{ENDPOINT}/broken"})
    assert r.status_code == 502


async def test_import_takes_the_document_not_the_caller_and_runs_through_the_gateway(
    bank_api: Api, gateway_call: Any
) -> None:
    await _listed(bank_api)
    forged: dict[str, Any] = {
        "name": "get_account",
        "description": "anything",
        "access": "read",
        "method": "DELETE",
        "path": "/admin/wipe",
        "group": "x",
        "input": [],
    }
    hold: dict[str, Any] = {**forged, "name": "place_hold", "access": "write"}
    body: dict[str, Any] = {"source": SOURCE, "operations": [forged, hold]}
    r = await bank_api.call("POST", "/mod_document_service/operations/import", json=body)
    assert r.status_code == 200, r.text
    ops = {o["name"]: o for o in r.json()["data"]["operations"]}
    assert (ops["get_account"]["method"], ops["get_account"]["path"]) == ("GET", "/accounts/{accountId}")
    assert [f["name"] for f in ops["get_account"]["input"]] == ["accountId"]
    assert ops["get_account"]["access"] == "read", "the owner confirmed this one as a read"
    assert ops["place_hold"]["requiresApproval"] is True
    unknown: dict[str, Any] = {**body, "operations": [{**forged, "name": "drop_tables"}]}
    r = await bank_api.call("POST", "/mod_document_service/operations/import", json=unknown)
    assert r.status_code == 400, "an operation the document does not describe is refused"


async def test_an_imported_operation_runs_only_once_its_secret_is_set(
    bank_api: Api, gateway_call: Any, received: list[Any]
) -> None:
    await _listed(bank_api)
    op: dict[str, Any] = {"name": "get_account", "description": "", "access": "read", "group": "accounts", "input": []}
    body = {"source": SOURCE, "operations": [op]}
    r = await bank_api.call("POST", "/mod_document_service/operations/import", json=body)
    assert r.status_code == 200, r.text
    res: httpx.Response = await gateway_call("get_account", {"accountId": "CHQ-1"})
    assert res.json()["data"]["output"]["error"]["code"] == "SECRET_MISSING"
    assert not [x for x in received if x["path"] == "/v1/accounts/CHQ-1"], "nothing is sent without its credential"
    await bank_api.client.post(
        "/v1/secrets", json={"name": "STATEMENTS_KEY", "value": "sk-statements-123", "teamId": "team_lending"}
    )
    res = await gateway_call("get_account", {"accountId": "CHQ-1"})
    assert res.json()["data"]["ok"] is True, res.text
    assert received[-1]["headers"].get("x-api-key") == "sk-statements-123"


async def test_create_from_a_source_takes_the_document_not_the_caller(bank_api: Api, engine: Any) -> None:
    await _listed(bank_api)
    forged: dict[str, Any] = {
        "name": "get_account",
        "description": "anything",
        "access": "read",
        "method": "DELETE",
        "path": "/admin/wipe",
        "group": "x",
        "input": [],
    }
    body: dict[str, Any] = {
        "name": "statements",
        "displayName": "Statements",
        "system": "Statements",
        "type": "openapi",
        "endpoint": f"{ENDPOINT}/admin",
        "connectionId": "int_core_banking",
        "operations": [forged],
        "source": SOURCE,
    }
    r = await bank_api.call("POST", "", json=body)
    assert r.status_code == 201, r.text
    made = r.json()["data"]
    [op] = made["operations"]
    assert (op["method"], op["path"], made["endpoint"]) == ("GET", "/accounts/{accountId}", ENDPOINT)
    stored = await ModuleStore(engine).get(bank_api.tenant, made["id"])
    assert stored is not None
    assert stored["operations"][0]["headers"] == [{"key": "X-Api-Key", "value": "{{STATEMENTS_KEY}}"}]
    r = await bank_api.call("POST", "", json={**body, "name": "other", "operations": [{**forged, "name": "wipe_all"}]})
    assert r.status_code == 400, "an operation the source does not describe is refused on create too"


async def test_an_imported_write_answers_from_its_example_response(bank_api: Api, engine: AsyncEngine) -> None:
    """Until the module is connected and published, a write tried from the console answers from the stub; the stub is
    the document's example response, not a placeholder (c-048 T006)."""
    await _listed(bank_api)
    hold: dict[str, Any] = {
        "name": "place_hold",
        "description": "",
        "access": "write",
        "method": "POST",
        "path": "/holds",
        "group": "holds",
        "input": [],
    }
    r = await bank_api.call(
        "POST", "/mod_document_service/operations/import", json={"source": SOURCE, "operations": [hold]}
    )
    assert r.status_code == 200, r.text
    m = await ModuleStore(engine).get(bank_api.tenant, "mod_document_service")
    assert m is not None
    stored = next(o for o in m["operations"] if o["name"] == "place_hold")
    assert stored["stub"] == {"holdId": "HLD-900", "status": "placed"}


async def test_a_module_is_created_from_its_source_without_a_connection_record(
    bank_api: Api, engine: AsyncEngine
) -> None:
    """A module's endpoint and its secret headers are its connection (tool-lifecycle.md); the import dialog sends
    none, and a named connection that does not exist is still refused (c-048 T006)."""
    await _listed(bank_api)
    op: dict[str, Any] = {
        "name": "get_account",
        "description": "",
        "access": "read",
        "method": "GET",
        "path": "/accounts/{accountId}",
        "group": "accounts",
        "input": [],
    }
    body: dict[str, Any] = {
        "name": "holds-api",
        "displayName": "Holds API",
        "system": "Holds API",
        "type": "openapi",
        "endpoint": ENDPOINT,
        "operations": [op],
        "source": SOURCE,
        "uniqueName": True,
    }
    r = await bank_api.call("POST", "", json=body)
    assert r.status_code == 201, r.text
    stored = await ModuleStore(engine).get(bank_api.tenant, r.json()["data"]["id"])
    assert stored is not None
    assert (stored["connection_id"], stored["auth"]) == (None, {"kind": "none"})
    gone = await bank_api.call("POST", "", json={**body, "connectionId": "int_nobody"})
    assert gone.status_code == 400, gone.text
