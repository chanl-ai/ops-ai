"""Import's presets (c-048 T006), by failure mode: access guessed from a name instead of the method, a document with no
auth imported silently so its calls go out with no credentials, and an imported write's stub answering a placeholder
instead of what the system's documentation shows."""

from __future__ import annotations

from typing import Any

from ops_tools.modules.openapi import discover
from ops_tools.modules.schemas import DiscoveryResult
from ops_tools.modules.service import ModuleService

URL = "https://api.bank.test/v1/openapi.json"


def doc(paths: dict[str, Any], *, secured: bool = False) -> dict[str, Any]:
    d: dict[str, Any] = {"openapi": "3.1.0", "info": {"title": "Bank", "version": "1"}, "paths": paths}
    if secured:
        d["components"] = {"securitySchemes": {"bankKey": {"type": "apiKey", "in": "header", "name": "X-Api-Key"}}}
        d["security"] = [{"bankKey": []}]
    return d


def test_access_comes_from_the_method_not_the_name() -> None:
    found = discover(
        doc(
            {
                "/accounts/{id}": {
                    "get": {"operationId": "closeAccountView"},
                },
                "/lookups": {"post": {"operationId": "getCustomer"}},
            }
        ),
        URL,
    )
    access = {o["name"]: o["access"] for o in found["operations"]}
    assert access == {"close_account_view": "read", "get_customer": "write"}


def test_a_document_with_no_auth_is_flagged_and_one_with_auth_is_not() -> None:
    paths = {"/accounts": {"get": {"operationId": "listAccounts"}}}
    bare = discover(doc(paths), URL)
    assert bare["noAuth"] is True
    assert any("no API key or bearer security scheme" in w for w in bare["warnings"])
    secured = discover(doc(paths, secured=True), URL)
    assert secured["noAuth"] is False
    assert not any("security scheme" in w for w in secured["warnings"])


def test_each_operation_is_stubbed_from_its_example_response() -> None:
    hold = {"id": "HLD-1", "status": "placed"}
    found = discover(
        doc(
            {
                "/holds": {
                    "post": {
                        "operationId": "placeHold",
                        "responses": {"201": {"content": {"application/json": {"example": hold}}}},
                    }
                },
                "/accounts": {
                    "get": {
                        "operationId": "listAccounts",
                        "responses": {
                            "200": {"content": {"application/json": {"examples": {"one": {"value": [{"id": "A1"}]}}}}}
                        },
                    }
                },
                "/ping": {"get": {"operationId": "pingBank", "responses": {"204": {"description": "No content"}}}},
            }
        ),
        URL,
    )
    stubs = {o["name"]: o.get("stub") for o in found["operations"]}
    assert stubs == {"place_hold": hold, "list_accounts": [{"id": "A1"}], "ping_bank": None}


def test_a_head_operation_is_skipped_with_a_warning_and_the_rest_still_discover() -> None:
    """HEAD answers no body, so it cannot be a tool; listing it must not fail the whole discovery."""
    found = discover(
        doc({"/accounts": {"get": {"operationId": "listAccounts"}, "head": {"operationId": "probe"}}}), URL
    )
    assert [o["name"] for o in found["operations"]] == ["list_accounts"]
    assert any(w.startswith("HEAD /accounts was skipped") for w in found["warnings"])
    DiscoveryResult.model_validate(ModuleService._public(found))  # pyright: ignore[reportPrivateUsage]
