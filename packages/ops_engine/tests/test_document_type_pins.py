"""Document type pins (c-236): a saved workflow follows "newest" after a newer version is saved (a step left without a
version), or a pin overwrites a version the builder chose."""

from __future__ import annotations

from typing import Any

from ops_engine.document_types import pinned, unpinned


def step(node_id: str, doc_type: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "ops.ai.extract",
        "typeVersion": 1,
        "parameters": {"file": "f", "documentType": doc_type},
    }


WIRE = {"nodes": [step("read", {"id": "levy_notice"}), step("again", {"id": "invoice", "version": 3})]}


def test_only_steps_without_a_version_are_pinned_and_a_chosen_version_stays() -> None:
    assert unpinned(WIRE) == {"levy_notice"}
    out = pinned(WIRE, {"levy_notice": 4, "invoice": 9})
    assert [n["parameters"]["documentType"] for n in out["nodes"]] == [
        {"id": "levy_notice", "version": 4},
        {"id": "invoice", "version": 3},
    ]
    assert WIRE["nodes"][0]["parameters"]["documentType"] == {"id": "levy_notice"}, "the input is left as it was"
