"""Extract a file, the shipped system_extract workflow, started the way Start run starts it: a file id and nothing
else. Detect is on, so a missing document type is a detect read, and a clean read is saved on the file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from ops_engine import default_registry
from ops_engine.compiler import channel, compile_definition
from ops_engine.definition import parse, validate
from ops_engine.journal import MemoryJournal
from ops_engine.node_types import start_form
from ops_engine.ports import EnginePorts

SEED = Path(__file__).resolve().parents[2] / "seed" / "event_workflows.json"
EXTRACT = next(w for w in json.loads(SEED.read_text()) if w["id"] == "system_extract")


class Files:
    def __init__(self) -> None:
        self.asked: list[dict[str, Any]] = []
        self.saved: list[tuple[str, dict[str, Any]]] = []

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        self.asked.append(request)
        return {
            "id": "ext_1",
            "status": "done",
            "outcome": "ok",
            "documentType": {"id": "supplier_invoice", "version": 1, "name": "Supplier invoice"},
            "needsReview": [],
        }

    async def purge(self, run_id: str, file_id: str) -> dict[str, Any]:
        return {}

    async def set_data(self, run_id: str, file_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self.saved.append((file_id, data))
        return {"data": data}


def test_start_run_asks_for_a_file_and_the_definition_passes() -> None:
    form = start_form(EXTRACT, default_registry())
    assert form is not None and form["takesFiles"] is True
    assert form["schema"]["required"] == ["fileId"]
    assert form["schema"]["properties"]["fileId"]["format"] == "file"
    assert validate(parse(EXTRACT), default_registry()) == []


async def test_a_file_and_no_type_is_detected_and_the_run_ends_saved() -> None:
    files = Files()
    ports = EnginePorts(tools=None, reviews=None, documents=files, file_data=files)  # type: ignore[arg-type]
    graph = compile_definition(
        parse(EXTRACT), default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver()
    )
    cfg: Any = {"configurable": {"thread_id": "sx1", "run_id": "sx1", "lease_generation": 1}}
    await graph.ainvoke({"input": {"fileId": "fil_1"}}, cfg, durability="sync")
    values = dict((await graph.aget_state(cfg)).values)
    assert files.asked == [{"detect": True, "ocr": True, "reviewBelow": None}]
    assert files.saved[0][0] == "fil_1"
    assert files.saved[0][1]["typeId"] == "supplier_invoice"
    assert files.saved[0][1]["typeName"] == "Supplier invoice"
    assert values[channel("saved")]["out"]["outcome"] == "saved"
    assert (await graph.aget_state(cfg)).interrupts == ()
