"""The OpenAPI gate every service runs: its document is complete and committed, which is what a generated SDK is built
from. A service's `scripts/check_openapi.py` builds its app's document and calls `report`.

Findings: an operation with no operationId or tag, a repeated operationId, a request body that is a bare object, a
success response with no schema that is not on the untyped allowlist, an allowlisted operation that is typed now, an
allowlist whose header disagrees with its lines or whose count grew against the committed one, and a committed
openapi.json that differs from the app's document. Used by scripts and tests only (the `testing` extra), never by a
running service."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from openapi_spec_validator import validate

HEADER = re.compile(r"^# (\d+) untyped operations")
METHODS = ("get", "post", "put", "patch", "delete")


def render(doc: dict[str, Any]) -> str:
    return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def bare(schema: dict[str, Any]) -> bool:
    return schema.get("type") == "object" and "properties" not in schema and "$ref" not in schema


def typed(op: dict[str, Any]) -> bool:
    """Whether a success response declares a schema, in JSON or any other media type it names (a SAML metadata
    document); a 204, a server-sent event stream and a redirect (a route a browser is sent through, such as a sign-in
    callback, has no body) count as typed."""
    for status, r in op["responses"].items():
        if status in ("301", "302", "303", "307", "308"):
            return True
        if not status.startswith("2"):
            continue
        content: dict[str, Any] = r.get("content") or {}
        if status == "204" or "text/event-stream" in content:
            return True
        media: dict[str, Any]
        for media in content.values():
            if media and media.get("schema") not in (None, {}):
                return True
    return False


def allowlist(text: str) -> tuple[int | None, set[str]]:
    lines = text.splitlines()
    header = HEADER.match(lines[0]) if lines else None
    entries = {line.strip() for line in lines[1:] if line.strip() and not line.startswith("#")}
    return (int(header.group(1)) if header else None), entries


def committed_count(repo_path: str, cwd: Path) -> int | None:
    """The allowlist count at HEAD for `repo_path` (relative to the repository root); None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "show", f"HEAD:{repo_path}"], cwd=cwd, capture_output=True, text=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    return allowlist(out)[0]


def problems(doc: dict[str, Any], *, allowlist_path: Path, document_path: Path, committed: int | None) -> list[str]:
    out: list[str] = []
    try:
        validate(doc)  # pyright: ignore[reportArgumentType]
    except Exception as e:
        out.append(f"not a valid OpenAPI document: {e}")
    seen: dict[str, str] = {}
    untyped: set[str] = set()
    for path, ops in doc["paths"].items():
        for method in METHODS:
            op = ops.get(method)
            if op is None:
                continue
            where = f"{method.upper()} {path}"
            oid = op.get("operationId")
            if not oid:
                out.append(f"{where}: no operationId")
                continue
            if oid in seen:
                out.append(f"{where}: operationId {oid} repeats {seen[oid]}")
            seen[oid] = where
            if not op.get("tags"):
                out.append(f"{oid}: no tag")
            body = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
            if body is not None and bare(body):
                out.append(f"{oid}: request body is a bare object; give it a model")
            if not typed(op):
                untyped.add(oid)
    count, listed = allowlist(allowlist_path.read_text()) if allowlist_path.exists() else (None, set[str]())
    out += [
        f"{oid}: success response has no schema; type it (it is not on the allowlist)"
        for oid in sorted(untyped - listed)
    ]
    out += [f"{oid}: on the allowlist but typed now; remove it" for oid in sorted(listed - untyped)]
    if count != len(listed):
        out.append(f"{allowlist_path.name}: the header says {count} and the file lists {len(listed)}")
    if committed is not None and count is not None and count > committed:
        name = allowlist_path.name
        out.append(f"{name}: {count} untyped operations, more than the {committed} committed; type routes instead")
    if not document_path.exists() or document_path.read_text() != render(doc):
        out.append(f"{document_path.name} differs from the app's document; run with --write and commit it")
    return out


def report(
    doc: dict[str, Any], *, allowlist_path: Path, document_path: Path, committed: int | None, write: bool
) -> tuple[int, list[str]]:
    """Writes the document when asked, then returns the exit code and the lines the calling script prints."""
    if write:
        document_path.write_text(render(doc))
    found = problems(doc, allowlist_path=allowlist_path, document_path=document_path, committed=committed)
    if found:
        return 1, [f"openapi: {p}" for p in found]
    ops = sum(1 for ops in doc["paths"].values() for m in METHODS if m in ops)
    return 0, [f"openapi: {ops} operations, {allowlist(allowlist_path.read_text())[0]} untyped on the allowlist"]
