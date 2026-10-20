"""Document type pins in a workflow definition (c-236): an Extract from file step may name a team's document type
without a version; saving the workflow writes the newest version into the step, so the saved definition (and its
digest) reads with that version until the workflow is saved again, whatever versions are added after."""

from __future__ import annotations

import copy
from typing import Any, cast

EXTRACT = "ops.ai.extract"


def _steps(wire: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = cast(list[dict[str, Any]], wire.get("nodes") or [])
    return [n for n in nodes if n.get("type") == EXTRACT and isinstance(n.get("parameters"), dict)]


def unpinned(wire: dict[str, Any]) -> set[str]:
    """The ids of the document types steps name without a version."""
    out: set[str] = set()
    for n in _steps(wire):
        doc_type = cast(dict[str, Any], n["parameters"]).get("documentType")
        if isinstance(doc_type, dict) and cast(dict[str, Any], doc_type).get("version") is None:
            type_id = str(cast(dict[str, Any], doc_type)["id"])
            if not type_id.startswith("$."):  # a path names the run's type, never a saved one to pin
                out.add(type_id)
    return out


def pinned(wire: dict[str, Any], versions: dict[str, int]) -> dict[str, Any]:
    """A copy of the definition with each unpinned document type given its version from `versions`."""
    out = copy.deepcopy(wire)
    for n in _steps(out):
        doc_type = cast(dict[str, Any], n["parameters"]).get("documentType")
        if isinstance(doc_type, dict):
            ref = cast(dict[str, Any], doc_type)
            if ref.get("version") is None and str(ref["id"]) in versions:
                ref["version"] = versions[str(ref["id"])]
    return out
