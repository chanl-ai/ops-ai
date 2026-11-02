"""A plugin version's tool declarations, their digest, and what changed between two versions (c-609).

A team runs the plugin version it took: tools-service keeps that version's declarations on the team's binding and
builds each call from them, so an upgrade changes nothing until the team takes it. The declarations are the plugin-wide
headers and each tool's manifest entry, as JSON with defaults left out, which is everything a data tool's request is
built from. A Python tool's entry is kept too, but its function is always the installed package's."""

from __future__ import annotations

import hashlib
import json
from typing import Any, cast

from .manifest import Manifest, Tool

# A tool entry's fields that change what a call sends or how it is decided, named in the review as they change.
COMPARED = ("request", "headers", "access", "requires_approval", "amount_max", "transform", "function", "needs_person",
            "scopes", "knowledge")  # fmt: skip
INPUT_COMPARED = ("type", "required", "enum", "format", "default", "pattern", "properties", "items", "max_items")


def declarations(manifest: Manifest) -> dict[str, Any]:
    """The version's declarations: plugin-wide headers and every tool's entry, defaults left out."""
    return {
        "version": manifest.version,
        "headers": dict(manifest.headers),
        "tools": [t.model_dump(mode="json", exclude_defaults=True) for t in manifest.tools],
    }


def digest(decl: dict[str, Any]) -> str:
    """The sha256 of the declarations' canonical JSON, the version number left out: a republished package with the
    same tools has the same digest, and one with changed tools under the same number does not."""
    body = {k: v for k, v in decl.items() if k != "version"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tools_of(decl: dict[str, Any]) -> dict[str, Tool]:
    """The declarations' tools, by name, as the SDK's Tool model."""
    entries = cast(list[dict[str, Any]], decl.get("tools") or [])
    return {str(t["name"]): Tool.model_validate(t) for t in entries}


def headers_of(decl: dict[str, Any]) -> dict[str, str]:
    return {str(k): str(v) for k, v in cast(dict[str, Any], decl.get("headers") or {}).items()}


def _inputs(old: Tool, new: Tool) -> dict[str, list[str]]:
    added = sorted(set(new.input) - set(old.input))
    removed = sorted(set(old.input) - set(new.input))
    changed = sorted(
        n
        for n in set(old.input) & set(new.input)
        if any(getattr(old.input[n], f) != getattr(new.input[n], f) for f in INPUT_COMPARED)
    )
    return {"added": added, "removed": removed, "changed": changed}


def _entry(tool: Tool, change: str) -> dict[str, Any]:
    return {
        "name": tool.name,
        "title": tool.title or tool.name.replace("_", " "),
        "access": tool.access,
        "change": change,
        "python": tool.function is not None,
    }


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """What a team taking `new` over `old` would see change: whether the plugin-wide headers changed, and each tool
    that is new, changed or removed, with the inputs added, removed and changed and the other fields that changed. A
    tool whose entry is the same in both is not listed."""
    before, after = tools_of(old), tools_of(new)
    tools: list[dict[str, Any]] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            inputs = {"added": sorted(after[name].input), "removed": [], "changed": []}
            tools.append({**_entry(after[name], "new"), "inputs": inputs, "changed": []})
        elif name not in after:
            tools.append({**_entry(before[name], "removed"), "inputs": {"added": [], "removed": [], "changed": []},
                          "changed": []})  # fmt: skip
        else:
            o, n = before[name], after[name]
            inputs = _inputs(o, n)
            fields = [f for f in COMPARED if getattr(o, f) != getattr(n, f)]
            if fields or any(inputs.values()):
                tools.append({**_entry(n, "changed"), "inputs": inputs, "changed": fields})
    return {"headers": headers_of(old) != headers_of(new), "tools": tools}
