"""The two seeded workflows a person starts by uploading files. Both use the same start form and the same Detect
read. Levy documents only starts a Read one levy document run per file. Record what an attachment is reads the file
itself and saves it."""

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
from ops_engine.ports import EnginePorts, StartedRun

SEED = {
    w["id"]: w for w in json.loads((Path(__file__).resolve().parents[2] / "seed" / "engine_workflows.json").read_text())
}


class Files:
    def __init__(self) -> None:
        self.asked: list[tuple[str, dict[str, Any]]] = []
        self.saved: list[tuple[str, dict[str, Any]]] = []

    async def extract(self, run_id: str, file_id: str, request: dict[str, Any], *, key: str) -> dict[str, Any]:
        self.asked.append((file_id, request))
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


class Runs:
    def __init__(self) -> None:
        self.started: list[tuple[str, dict[str, Any]]] = []

    async def start(self, parent_run_id: str, workflow: str, input: dict[str, Any], key: str) -> StartedRun:
        self.started.append((workflow, input))
        return StartedRun(f"wfrun_{len(self.started)}", True)


def _graph(name: str, ports: EnginePorts) -> Any:
    definition = parse({k: v for k, v in SEED[name].items() if k != "teamId"})
    assert validate(definition, default_registry()) == [], name
    return compile_definition(
        definition, default_registry(), ports=ports, journal=MemoryJournal(), checkpointer=InMemorySaver()
    )


def test_both_start_forms_take_files() -> None:
    files = start_form(SEED["levy_files"], default_registry())
    one = start_form(SEED["attachment_record"], default_registry())
    assert files is not None and files["takesFiles"] and files["schema"]["required"] == ["files"]
    assert one is not None and one["takesFiles"] and one["schema"]["properties"]["fileId"]["format"] == "file"


async def test_levy_files_starts_one_read_per_uploaded_file() -> None:
    runs = Runs()
    ports = EnginePorts(tools=None, reviews=None, runs=runs)  # type: ignore[arg-type]
    graph = _graph("levy_files", ports)
    cfg: Any = {"configurable": {"thread_id": "lf1", "run_id": "lf1", "lease_generation": 1}}
    uploaded = [{"fileId": "fil_1", "name": "notice.pdf"}, {"fileId": "fil_2", "name": "order.pdf"}]
    await graph.ainvoke({"input": {"files": uploaded}}, cfg, durability="sync")
    values = dict((await graph.aget_state(cfg)).values)
    assert runs.started == [
        ("levy_read_one", {"fileId": "fil_1", "name": "notice.pdf"}),
        ("levy_read_one", {"fileId": "fil_2", "name": "order.pdf"}),
    ]
    assert values[channel("started")]["out"]["outcome"] == "started"
    assert values[channel("each")]["out"]["count"] == 2


async def test_attachment_record_detects_the_file_and_ends_recorded() -> None:
    files = Files()
    ports = EnginePorts(tools=None, reviews=None, documents=files, file_data=files)  # type: ignore[arg-type]
    graph = _graph("attachment_record", ports)
    cfg: Any = {"configurable": {"thread_id": "ar1", "run_id": "ar1", "lease_generation": 1}}
    await graph.ainvoke({"input": {"fileId": "fil_9", "name": "invoice.pdf"}}, cfg, durability="sync")
    values = dict((await graph.aget_state(cfg)).values)
    assert files.asked == [("fil_9", {"detect": True, "ocr": True, "reviewBelow": None})]
    assert files.saved[0][0] == "fil_9"
    assert files.saved[0][1]["typeName"] == "Supplier invoice"
    assert values[channel("recorded")]["out"]["outcome"] == "recorded"
    assert (await graph.aget_state(cfg)).interrupts == ()
