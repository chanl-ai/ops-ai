"""Every seeded workflow that reads a file of a document type saves what it read on the file (c-378), by failure mode:
a workflow with no Save data on file step leaves Files saying "Not read" while the Fields tab shows the read (staging,
mail_document wfrun_d150e5be12e3); a step that saves only the ok path leaves a read waiting for a check unsaved; and a
step that names the type by its id shows "levy_notice" where the type's name belongs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

SEED = Path(__file__).resolve().parents[2] / "seed"
EXTRACT, SAVE, REVIEW = "ops.ai.extract", "ops.files.setData", "ops.flow.humanReview"


def _seeded() -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], w)
        for f in ("engine_workflows.json", "event_workflows.json")
        for w in cast(list[Any], json.loads((SEED / f).read_text()))
    ]


def _typed_reads(w: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract steps that read a file as a document type: one named, or Detect's. A read with fields of its own names
    no type, and there is nothing to show for the file."""
    return [
        n
        for n in w["nodes"]
        if n["type"] == EXTRACT and (n["parameters"].get("documentType") or n["parameters"].get("detect"))
    ]


def _saves(w: dict[str, Any], start: str, port: str, read: str) -> bool:
    """`start`'s `port` leads to a Save data on file step of `read`'s output, directly or through a person's check."""
    nodes = {n["id"]: n for n in w["nodes"]}
    nxt = [c["to"]["node"] for c in w["connections"] if c["from"] == {"node": start, "port": port}]
    for node in (nodes[i] for i in nxt):
        if node["type"] == SAVE and node["parameters"].get("read") == f"$.nodes.{read}.out":
            return True
        if node["type"] == REVIEW and _saves(w, node["id"], "approve", read):
            return True
    return False


def test_every_seeded_typed_read_is_saved_on_the_file_on_both_paths() -> None:
    missing = [
        f"{w['id']}.{n['id']}.{port}"
        for w in _seeded()
        for n in _typed_reads(w)
        for port in ("ok", "review")
        if not _saves(w, n["id"], port, n["id"])
    ]
    assert missing == [], missing


def test_no_seeded_save_names_the_type_by_its_id() -> None:
    by_id = [
        f"{w['id']}.{n['id']}"
        for w in _seeded()
        for n in w["nodes"]
        if n["type"] == SAVE and str(n["parameters"].get("typeName") or "").endswith(".documentType.id")
    ]
    assert by_id == [], by_id
