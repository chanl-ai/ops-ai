"""The Save data on file and Purge steps (c-250), by failure mode: Save data writing data made up for the file when the
read names no document type or extraction, or counting fields as waiting after a person checked them (F2); Purge
asking for another file than the deleted one (F4)."""

from __future__ import annotations

from typing import Any

from ops_engine.compiler import NodeCall, documents_purge, files_set_data
from ops_engine.definition import NodeInstance
from ops_engine.node_types import default_registry
from ops_engine.ports import EnginePorts

READ = {
    "documentType": {"id": "restraining_notice", "version": 2},
    "extractionId": "ext_1",
    "needsReview": ["ssn_full", "debtor_address"],
}


class Ports:
    def __init__(self) -> None:
        self.saved: list[tuple[str, dict[str, Any]]] = []
        self.purged: list[str] = []

    async def set_data(self, run_id: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.saved.append((file_id, data))
        return {"data": data}

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        self.purged.append(file_id)
        return {"extractions": 2, "samples": 1}


def call(kind: str, ports: Ports, **params: Any) -> NodeCall:
    node = NodeInstance.model_validate({"id": "step", "type": kind, "typeVersion": 1})
    return NodeCall(
        run_id="run_1",
        node=node,
        type=default_registry().get(kind, 1),
        iteration=0,
        attempt=1,
        key="run_1:step:0:1",
        params=params,
        generation=None,
        ports=EnginePorts(tools=None, reviews=None, documents=ports, file_data=ports),  # type: ignore[arg-type]
        run_input={},
        scope={},
    )


async def test_save_data_records_the_read_and_a_checked_read_has_nothing_waiting() -> None:
    ports = Ports()
    unchecked = await files_set_data(call("ops.files.setData", ports, file="fil_1", read=READ, typeName="Notice"))
    checked = await files_set_data(call("ops.files.setData", ports, file="fil_1", read=READ, checked=True))
    nothing = await files_set_data(call("ops.files.setData", ports, file="fil_1", read={"needsReview": []}))
    [(fid, first), (_, second)] = ports.saved
    assert (unchecked.port, checked.port, nothing.port) == ("ok", "ok", "error"), nothing
    assert fid == "fil_1" and (first["typeId"], first["version"], first["path"]) == ("restraining_notice", 2, "model")
    assert (first["fieldsToCheck"], first["typeName"], first["extractionId"]) == (2, "Notice", "ext_1"), first
    assert second["fieldsToCheck"] == 0 and "typeName" not in second, second


async def test_a_template_read_is_saved_with_its_path_and_template() -> None:
    """c-253: the files list shows which form a file was read as."""
    ports = Ports()
    read = {**READ, "path": "template", "templateId": "tpl_invoice_a"}
    await files_set_data(call("ops.files.setData", ports, file="fil_1", read=read))
    [(_, saved)] = ports.saved
    assert (saved["path"], saved["templateId"]) == ("template", "tpl_invoice_a"), saved


async def test_purge_removes_what_was_read_from_the_deleted_file() -> None:
    ports = Ports()
    done = await documents_purge(call("ops.documents.purge", ports, file="fil_gone"))
    assert (done.port, done.out, ports.purged) == ("ok", {"extractions": 2, "samples": 1}, ["fil_gone"])


async def test_a_detect_read_is_saved_as_the_kind_found_or_as_not_recognised() -> None:
    """c-335: a Detect read names the kind it found, so the files list shows it; one that found none of the team's
    types is saved with no type, never refused, so the file shows it was read and not recognised."""
    ports = Ports()
    found = {**READ, "classification": {"typeId": "restraining_notice", "name": "Restraining notice"}}
    unknown = {"extractionId": "ext_2", "needsReview": ["documentType"], "classification": {"typeId": None}}
    first = await files_set_data(call("ops.files.setData", ports, file="fil_1", read=found))
    second = await files_set_data(call("ops.files.setData", ports, file="fil_2", read=unknown, checked=True))
    [(_, named), (_, unnamed)] = ports.saved
    assert (first.port, second.port) == ("ok", "ok"), second
    assert (named["typeId"], named["typeName"]) == ("restraining_notice", "Restraining notice"), named
    assert (unnamed["typeId"], unnamed["version"], unnamed["extractionId"]) == (None, None, "ext_2"), unnamed
    assert "typeName" not in unnamed and unnamed["fieldsToCheck"] == 0, unnamed
