"""The Extract from file step (c-157, c-235) on documents-service's extraction API, by failure mode: the step's outputs
changing shape when the answer moved to the API (workflows read `fields`, `records`, `needsReview`, `floor` and
`schema`); a review answer taking the ok port; an unreadable scan passing as found; a schema error crashing the step
instead of taking the error port; a failure files-service may get past on a retry (the floor out of reach) taking a
port instead of being retried; a retry asking for a new extraction instead of reading the same one; a state the step
does not know turned into a port it does not have; the step writing to the file, which is Save data on file's job
(c-378)."""

from __future__ import annotations

from typing import Any

import pytest

from ops_engine.compiler import NodeCall, ai_extract, files_set_data
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.ports import EnginePorts

FIELDS: list[dict[str, Any]] = [
    {"key": "invoice_no", "type": "text", "required": True},
    {"key": "amount", "type": "money", "required": True},
]
SCORED = {
    "fileId": "fil_1",
    "fields": {"invoice_no": {"value": "INV-2219", "confidence": 1.0, "needsReview": False}},
    "needsReview": [],
    "floor": 0.8,
    "schema": [{"key": "invoice_no", "label": "invoice_no", "type": "text", "required": True}],
}


class Files:
    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        self.asked: list[tuple[str, dict[str, Any], str]] = []
        self.saved: list[tuple[str, dict[str, Any]]] = []

    async def set_data(self, run_id: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.saved.append((file_id, data))
        return {"data": data}

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        self.asked.append((file_id, request, key))
        return self.answer

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        return {}


def call(files: Files, **params: Any) -> NodeCall:
    node = NodeInstance.model_validate({"id": "extract", "type": "ops.ai.extract", "typeVersion": 1})
    return NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get("ops.ai.extract", 1),
        iteration=0,
        attempt=1,
        key="run_1:extract:0:1",
        params={"file": "fil_1", "fields": FIELDS, **params},
        generation=None,
        ports=EnginePorts(tools=None, reviews=None, documents=files, file_data=files),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )


async def test_a_done_answer_is_the_steps_output_and_the_request_carries_the_steps_settings() -> None:
    files = Files({"id": "ext_1", "status": "done", "outcome": "ok", "corrections": [], **SCORED})
    out = await ai_extract(call(files, many=True, ocr=True, reviewBelow=0.9))
    assert out.port == "ok" and out.out == SCORED | {"extractionId": "ext_1"}, out
    # The step key, without the attempt, so a retried step reads the same extraction.
    assert files.asked == [
        ("fil_1", {"fields": FIELDS, "many": True, "ocr": True, "reviewBelow": 0.9}, "run_1:extract:0")
    ]


async def test_a_field_below_the_floor_takes_review() -> None:
    review = {**SCORED, "needsReview": ["invoice_no"]}
    out = await ai_extract(call(Files({"id": "ext_1", "status": "done", "outcome": "review", **review})))
    assert out.port == "review" and out.out["needsReview"] == ["invoice_no"], out


async def test_an_unreadable_file_takes_the_unreadable_port() -> None:
    answer = {"id": "ext_1", "status": "unreadable", "outcome": "unreadable", "fileId": "fil_1", "pages": 2}
    out = await ai_extract(call(Files(answer)))
    assert out.port == "unreadable" and out.out == {"fileId": "fil_1", "pages": 2, "extractionId": "ext_1"}, out


async def test_a_schema_error_takes_the_error_port() -> None:
    error = {"code": "schema_error", "message": "The answer did not match the fields asked for.", "details": ["x"]}
    out = await ai_extract(call(Files({"id": "ext_1", "status": "failed", "fileId": "fil_1", "error": error})))
    assert out.port == "error" and out.out["code"] == "schema_error" and out.out["details"] == ["x"], out


async def test_a_floor_out_of_reach_is_raised_so_the_step_is_retried() -> None:
    error = {"code": "floor_unread", "message": "The extractionFloor policy could not be read"}
    with pytest.raises(RuntimeError, match="floor_unread"):
        await ai_extract(call(Files({"id": "ext_1", "status": "failed", "fileId": "fil_1", "error": error})))


@pytest.mark.parametrize("answer", [{"status": "running"}, {"status": "done"}, {"status": "done", "outcome": "maybe"}])
async def test_a_state_the_step_does_not_know_is_raised(answer: dict[str, Any]) -> None:
    with pytest.raises(RuntimeError, match="documents-service answered"):
        await ai_extract(call(Files({"id": "ext_1", "fileId": "fil_1", **answer})))


async def test_a_document_type_step_asks_for_the_type_and_its_pinned_version() -> None:
    files = Files({"id": "ext_1", "status": "done", "outcome": "ok", **SCORED})
    await ai_extract(call(files, documentType={"id": "levy_notice", "version": 2}, ocr=True))
    [(_, request, _)] = files.asked
    assert request == {"documentTypeId": "levy_notice", "version": 2, "ocr": True, "reviewBelow": None}, request


async def test_detect_asks_for_a_classified_read_and_an_unknown_kind_goes_to_review() -> None:
    """Extract with Detect (c-249): the step asks documents-service to classify the file first; a kind it cannot name
    takes review, so a person decides, never ok with no fields."""
    files = Files(
        {"id": "ext_1", "status": "done", "outcome": "unknown", "fields": {}, "needsReview": ["documentType"]}
    )
    node = NodeInstance.model_validate({"id": "extract", "type": "ops.ai.extract", "typeVersion": 1})
    step = NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get("ops.ai.extract", 1),
        iteration=0,
        attempt=1,
        key="run_1:extract:0:1",
        params={"file": "fil_1", "detect": True, "ocr": True},
        generation=None,
        ports=EnginePorts(tools=None, reviews=None, documents=files, file_data=files),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )
    out = await ai_extract(step)
    [(_, request, _)] = files.asked
    assert request == {"detect": True, "ocr": True, "reviewBelow": None} and out.port == "review", (request, out)


async def test_a_read_request_with_no_type_reads_with_detect() -> None:
    """The system extract workflow always passes documentType from its input (c-335): a request that named no type
    resolves it to an empty id, which must read with Detect, never ask documents-service for type None."""
    files = Files({"id": "ext_1", "status": "done", "outcome": "ok", **SCORED})
    await ai_extract(call(files, fields=[], documentType={"id": None, "version": None}, detect=True, ocr=True))
    await ai_extract(call(files, fields=[], documentType={"id": "levy_notice", "version": None}, detect=True, ocr=True))
    [(_, untyped, _), (_, typed, _)] = files.asked
    assert untyped == {"detect": True, "ocr": True, "reviewBelow": None}, untyped
    assert typed == {"documentTypeId": "levy_notice", "version": None, "ocr": True, "reviewBelow": None}, typed


async def test_the_extract_step_writes_nothing_to_the_file() -> None:
    """Recording a read on the file is the workflow's Save data on file step (c-378, tick 36): an Extract step that
    wrote it too gave every read a second writer, which a workflow could neither see nor turn off."""
    files = Files(
        {
            "id": "ext_7",
            "status": "done",
            "outcome": "review",
            "corrections": [],
            **SCORED,
            "needsReview": ["amount"],
            "documentType": {"id": "levy_notice", "version": 2, "name": "Levy notice"},
        }
    )
    await ai_extract(call(files, documentType={"id": "levy_notice", "version": 2}))
    assert files.saved == []


async def test_save_data_on_file_names_the_type_the_read_names() -> None:
    """A workflow that does not pass typeName still shows what the file was read as: documents-service names the type
    on the read (c-378 T001)."""
    files = Files({})
    read = {
        "extractionId": "ext_7",
        "needsReview": ["amount"],
        "documentType": {"id": "levy_notice", "version": 2, "name": "Levy notice"},
    }
    done = await files_set_data(call(files, read=read))
    assert done.port == "ok", done
    [(file_id, data)] = files.saved
    assert file_id == "fil_1" and (data["typeId"], data["version"], data["typeName"]) == (
        "levy_notice",
        2,
        "Levy notice",
    )
    assert (data["fieldsToCheck"], data["extractionId"], data["path"]) == (1, "ext_7", "model"), data
