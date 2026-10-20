"""What an operation answers, kept from its import (c-353), by failure mode: an import drops the success response's
schema, or keeps it with its references unresolved; an operation with only an example gives nothing to map from; a
tool's route leaves its output out."""

from __future__ import annotations

from typing import Any

from ops_tools.modules.openapi import discover
from ops_tools.registry import inferred

from .conftest import Api, service_headers

CUSTOMER = {"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"}}, "required": ["id"]}
SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Core", "version": "1"},
    "servers": [{"url": "https://core.example"}],
    "components": {"schemas": {"Customer": CUSTOMER}},
    "paths": {
        "/customers/{id}": {
            "get": {
                "operationId": "getCustomer",
                "parameters": [{"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}],
                "responses": {
                    "200": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/Customer"}}}}
                },
            }
        },
        "/holds": {
            "post": {
                "operationId": "placeHold",
                "responses": {
                    "201": {"content": {"application/json": {"example": {"holdId": "H-1", "status": "placed"}}}}
                },
            }
        },
    },
}


def test_an_import_keeps_the_success_response_schema_with_its_references_resolved() -> None:
    ops = {o["name"]: o for o in discover(SPEC, "https://core.example/openapi.json")["operations"]}
    assert ops["get_customer"]["response_schema"] == CUSTOMER
    assert "response_schema" not in ops["place_hold"] and ops["place_hold"]["stub"] == {
        "holdId": "H-1",
        "status": "placed",
    }


def test_an_example_gives_an_open_shape_with_its_keys() -> None:
    shape = inferred({"holdId": "H-1", "lines": [{"amount": 1}]})
    assert set(shape["properties"]) == {"holdId", "lines"} and "additionalProperties" not in shape
    assert set(shape["properties"]["lines"]["items"]["properties"]) == {"amount"}


async def test_a_tools_route_says_what_it_answers(api: Api) -> None:
    r = await api.client.get("/v1/tools/update_address", headers=service_headers(api.tenant))
    assert r.status_code == 200 and "outputSchema" in r.json()["data"], r.text
