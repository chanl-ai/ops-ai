"""Extract from file's "What to read" (c-535), by failure mode: a full-text or proposed read refused by the step's own
parameter check because it names no fields, type or Detect; the read choice dropped on its way to documents-service;
a full-text or proposed answer reshaped so later steps lose `text`, `pages` or `proposal`; and the field picker
offering the wrong outputs after such a step."""

from __future__ import annotations

from typing import Any

import jsonschema

from ops_engine.compiler import ai_extract
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.shapes import BUILDERS
from tests.test_extract_step import Files, call

EXTRACT = default_registry().get("ops.ai.extract", 1)
TEXT: dict[str, Any] = {
    "fileId": "fil_1",
    "text": "PURCHASE ORDER 88412\n\nRemittance advice",
    "pages": [{"number": 1, "text": "PURCHASE ORDER 88412", "tables": []}, {"number": 2, "text": "Remittance advice"}],
}
PROPOSED: dict[str, Any] = {
    "fileId": "fil_1",
    "proposal": {"name": "Purchase order", "fields": [{"key": "po_number", "label": "PO number", "type": "text"}]},
    "fields": {"po_number": {"value": "88412", "confidence": 0.97, "needsReview": False}},
    "needsReview": [],
    "floor": 0.8,
    "schema": [{"key": "po_number", "label": "PO number", "type": "text", "required": False}],
}


class Lookups:
    async def document_fields(self, type_id: str, version: int | None) -> list[dict[str, Any]]:
        return []

    async def operation_output(self, operation: str) -> None:
        return None


def test_a_full_text_or_proposed_read_needs_no_fields_type_or_detect() -> None:
    for params in ({"file": "$.input.file", "read": "text"}, {"file": "$.input.file", "read": "propose"}):
        jsonschema.validate(params, EXTRACT.parameters)
    for bad in ({"file": "$.input.file", "read": "everything"}, {"file": "$.input.file"}):
        try:
            jsonschema.validate(bad, EXTRACT.parameters)
        except jsonschema.ValidationError:
            continue
        raise AssertionError(f"{bad} passed the step's parameter check")


async def test_a_full_text_read_asks_for_text_and_leaves_with_the_pages() -> None:
    files = Files({"id": "ext_1", "status": "done", "outcome": "ok", **TEXT})
    out = await ai_extract(call(files, fields=[], read="text", maxPages=3))
    [(_, asked, _)] = files.asked
    assert asked["read"] == "text" and asked["maxPages"] == 3 and "fields" not in asked, asked
    assert out.port == "ok" and out.out == TEXT | {"extractionId": "ext_1"}, out


async def test_a_proposed_read_carries_the_hint_and_leaves_with_the_proposal() -> None:
    files = Files({"id": "ext_2", "status": "done", "outcome": "ok", **PROPOSED})
    out = await ai_extract(call(files, fields=[], read="propose", hint="a purchase order", proposePages=2))
    [(_, asked, _)] = files.asked
    assert (asked["read"], asked["hint"], asked["proposePages"]) == ("propose", "a purchase order", 2), asked
    assert "fields" not in asked, asked
    assert out.port == "ok" and out.out["proposal"] == PROPOSED["proposal"] and out.out["extractionId"] == "ext_2"


async def test_the_field_picker_offers_text_and_pages_or_the_proposal() -> None:
    build = BUILDERS[EXTRACT.executor]
    text = NodeInstance.model_validate(
        {"id": "read", "type": "ops.ai.extract", "typeVersion": 1, "parameters": {"file": "f", "read": "text"}}
    )
    proposed = NodeInstance.model_validate(
        {"id": "read", "type": "ops.ai.extract", "typeVersion": 1, "parameters": {"file": "f", "read": "propose"}}
    )
    text_ok = (await build(text, EXTRACT, Lookups()))["ok"]  # type: ignore[arg-type]
    proposed_ok = (await build(proposed, EXTRACT, Lookups()))["ok"]  # type: ignore[arg-type]
    assert {"text", "pages"} <= set(text_ok.get("properties", {})) and "fields" not in text_ok.get("properties", {})
    assert {"proposal", "fields"} <= set(proposed_ok.get("properties", {})), proposed_ok
