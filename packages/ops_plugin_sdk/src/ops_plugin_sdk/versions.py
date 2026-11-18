"""A plugin version's tool declarations, their digest, and what changed between two versions.

A team runs the plugin version it took: tools-service keeps that version's declarations on the team's binding and
builds each call from them, so an upgrade changes nothing until the team takes it. The declarations are the plugin-wide
headers and each tool's manifest entry, as JSON with defaults left out, which is everything a data tool's request is
built from. A Python tool's entry is kept too, but its function is always the installed package's."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TypedDict, cast

from pydantic import JsonValue

from .manifest import Manifest, Tool

# A tool entry's fields that change what a call sends or how it is decided, named in the review as they change.
COMPARED = ("request", "headers", "access", "requires_approval", "amount_max", "transform", "function", "needs_person",
            "scopes", "knowledge")  # fmt: skip
INPUT_COMPARED = ("type", "required", "enum", "format", "default", "pattern", "properties", "items", "max_items")


class InputChanges(TypedDict):
    added: list[str]
    removed: list[str]
    changed: list[str]


class ToolChange(TypedDict):
    name: str
    title: str
    access: str
    change: str
    python: bool
    inputs: InputChanges
    changed: list[str]


class VersionDiff(TypedDict):
    headers: bool
    tools: list[ToolChange]


def declarations(manifest: Manifest, root: Path | None = None) -> dict[str, JsonValue]:
    """The version's declarations: plugin-wide headers and every tool's entry, defaults left out. Given the plugin's
    folder, each template's file is hashed in too, so a release that changes only a skill or an agent is an update."""
    out: dict[str, JsonValue] = {
        "version": manifest.version,
        "headers": dict(manifest.headers),
        "tools": [t.model_dump(mode="json", exclude_defaults=True) for t in manifest.tools],
    }
    if root is not None and manifest.templates:
        out["templates"] = {t.id: _file_digest(root / t.path) for t in manifest.templates}
    return out


def _file_digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def digest(decl: dict[str, JsonValue]) -> str:
    """The sha256 of the declarations' canonical JSON, the version number left out: a republished package with the
    same tools has the same digest, and one with changed tools under the same number does not."""
    body = {k: v for k, v in decl.items() if k != "version"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def tools_of(decl: dict[str, JsonValue]) -> dict[str, Tool]:
    """The declarations' tools, by name, as the SDK's Tool model."""
    entries = cast(list[dict[str, JsonValue]], decl.get("tools") or [])
    return {str(t["name"]): Tool.model_validate(t) for t in entries}


def headers_of(decl: dict[str, JsonValue]) -> dict[str, str]:
    return {str(k): str(v) for k, v in cast(dict[str, JsonValue], decl.get("headers") or {}).items()}


def _inputs(old: Tool, new: Tool) -> InputChanges:
    added = sorted(set(new.input) - set(old.input))
    removed = sorted(set(old.input) - set(new.input))
    changed = sorted(
        n
        for n in set(old.input) & set(new.input)
        if any(getattr(old.input[n], f) != getattr(new.input[n], f) for f in INPUT_COMPARED)
    )
    return InputChanges(added=added, removed=removed, changed=changed)


def _entry(tool: Tool, change: str, inputs: InputChanges, changed: list[str]) -> ToolChange:
    return {
        "name": tool.name,
        "title": tool.title or tool.name.replace("_", " "),
        "access": tool.access,
        "change": change,
        "python": tool.function is not None,
        "inputs": inputs,
        "changed": changed,
    }


def diff(old: dict[str, JsonValue], new: dict[str, JsonValue]) -> VersionDiff:
    """What a team taking `new` over `old` would see change: whether the plugin-wide headers changed, and each tool
    that is new, changed or removed, with the inputs added, removed and changed and the other fields that changed. A
    tool whose entry is the same in both is not listed."""
    before, after = tools_of(old), tools_of(new)
    tools: list[ToolChange] = []
    for name in sorted(set(before) | set(after)):
        if name not in before:
            inputs = InputChanges(added=sorted(after[name].input), removed=[], changed=[])
            tools.append(_entry(after[name], "new", inputs, []))
        elif name not in after:
            tools.append(_entry(before[name], "removed", InputChanges(added=[], removed=[], changed=[]), []))
        else:
            o, n = before[name], after[name]
            inputs = _inputs(o, n)
            fields = [f for f in COMPARED if getattr(o, f) != getattr(n, f)]
            if fields or any(inputs.values()):
                tools.append(_entry(n, "changed", inputs, fields))
    return VersionDiff(headers=headers_of(old) != headers_of(new), tools=tools)
