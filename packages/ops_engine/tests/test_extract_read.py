"""Extract from file's "What to read", by failure mode: a full-text or proposed read refused by the step's own
parameter check because it names no fields, type or Detect; a full-text read asking extractions instead of the file's
shared reading, or keeping pages past maxPages; a reading still under way polled instead of parked; a failed reading
raised instead of taking the error port; the read choice dropped on its way to documents-service; a proposed answer
reshaped so later steps lose `proposal`; and the field picker offering the wrong outputs after such a step."""

from __future__ import annotations

from typing import Any

import jsonschema
import pytest

from ops_engine import compiler
from ops_engine.compiler import ai_extract
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.shapes import BUILDERS
from tests.test_extract_step import Files, call

EXTRACT = default_registry().get("ops.ai.extract", 1)
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


def _reading(status: str, pages: int = 0) -> dict[str, Any]:
    """The file's shared reading as documents-service answers it, `pages` pages long once done."""
    answer: dict[str, Any] = {
        "fileId": "fil_1", "digest": "d" * 64, "status": status, "readerVersion": "r1",
        "settings": {"ocr": "auto", "language": "eng"}, "pagesTotal": pages or None, "pagesDone": pages,
    }  # fmt: skip
    if status == "done":
        table = {"id": "b2", "kind": "table", "text": "", "cells": [{"row": 0, "col": 0, "text": "Due", "box": None}]}
        answer["pages"] = [
            {"number": n, "source": "ocr", "text": f"Page {n} of {pages}", "blocks": [table], "words": [{"t": "w"}]}
            for n in range(1, pages + 1)
        ]
    return answer


class Parked(Exception):
    """What interrupt() does to the step in a real run: the pass ends there, and a resume runs the step again."""


async def test_a_full_text_read_is_the_shared_reading_trimmed_to_max_pages() -> None:
    """Full text asked extractions for `read: text`, which documents-service refuses with a 400: the step now reads
    the file's one reading and keeps only the pages asked for, each with its text and tables."""
    files = Files({}, reading=_reading("done", 3))
    out = await ai_extract(call(files, fields=[], read="text", ocr=True, maxPages=2))
    assert files.asked == [] and files.read == [("fil_1", "auto")], (files.asked, files.read)
    assert out.port == "ok", out
    assert out.out == {
        "fileId": "fil_1",
        "text": "Page 1 of 3\n\nPage 2 of 3",
        "pages": [
            {"number": n, "text": f"Page {n} of 3", "tables": [{"cells": [{"row": 0, "col": 0, "text": "Due"}]}]}
            for n in (1, 2)
        ],
        "readPages": 2,
    }, out


async def test_a_reading_still_under_way_parks_on_reading_finished_and_reads_it_when_woken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long scan is read in the background: the step parks on documents-service's reading.finished under the key
    that event is posted with, never polls, and on the resumed pass reads the finished reading."""
    parked: list[dict[str, Any]] = []

    def interrupt(payload: dict[str, Any]) -> dict[str, Any]:
        parked.append(payload)
        raise Parked

    monkeypatch.setattr(compiler, "interrupt", interrupt)
    files = Files({}, reading=_reading("reading"))
    with pytest.raises(Parked):
        await ai_extract(call(files, fields=[], read="text", ocr=True))
    key = f"reading.finished:{'d' * 64}:r1:auto:eng:fil_1"
    assert [(p["kind"], p["event"], p["key"], p["timeoutSeconds"]) for p in parked] == [
        ("external", "reading.finished", key, 1200.0)
    ], parked
    files.reading_answer = _reading("done", 2)
    out = await ai_extract(call(files, fields=[], read="text", ocr=True))
    assert out.port == "ok" and out.out["text"] == "Page 1 of 2\n\nPage 2 of 2", out
    assert len(files.read) == 2 and files.asked == [], files.read


async def test_a_failed_reading_takes_the_error_port_with_its_reason() -> None:
    files = Files({}, reading=_reading("failed") | {"error": {"code": "too_many_tries", "message": "Gave up"}})
    out = await ai_extract(call(files, fields=[], read="text"))
    assert files.read == [("fil_1", "off")], files.read
    assert out.port == "error" and out.out == {"error": "Gave up", "code": "too_many_tries"}, out


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
    text_ok: dict[str, Any] = (await build(text, EXTRACT, Lookups()))["ok"]  # type: ignore[arg-type]
    proposed_ok: dict[str, Any] = (await build(proposed, EXTRACT, Lookups()))["ok"]  # type: ignore[arg-type]
    assert {"text", "pages"} <= set(text_ok.get("properties", {})) and "fields" not in text_ok.get("properties", {})
    assert {"proposal", "fields"} <= set(proposed_ok.get("properties", {})), proposed_ok
