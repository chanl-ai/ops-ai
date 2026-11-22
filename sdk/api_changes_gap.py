"""Lists every operation whose parameters, request body or replies differ between a base ref and the working tree's
committed services/*/openapi.json, and is not named in docs/architecture/migration/api-changes.md.

    uv run python sdk/api_changes_gap.py [base-ref]      (default origin/develop; exit 1 when a route is missing)

Schema names and descriptions are ignored: only the structure a caller sees counts. /health routes are skipped.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "architecture" / "migration" / "api-changes.md"
SKIP = {"description", "title", "example", "examples", "summary", "operationId"}
VERBS = ("get", "post", "put", "patch", "delete")


def load(ref: str, service: str) -> dict[str, Any] | None:
    shown = subprocess.run(
        ["git", "show", f"{ref}:services/{service}/openapi.json"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def resolve(doc: dict[str, Any], node: Any, seen: tuple[str, ...] = ()) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].split("/")[-1]
            if name in seen:
                return "$cycle"
            return resolve(doc, doc["components"]["schemas"].get(name), (*seen, name))
        return {k: resolve(doc, v, seen) for k, v in node.items() if k not in SKIP}
    if isinstance(node, list):
        return [resolve(doc, v, seen) for v in node]
    return node


def signature(doc: dict[str, Any], op: dict[str, Any]) -> str:
    params = sorted(op.get("parameters", []), key=lambda p: (p.get("in", ""), p.get("name", "")))
    return json.dumps(
        resolve(doc, {"p": params, "b": op.get("requestBody"), "r": op.get("responses", {})}), sort_keys=True
    )


def shape(path: str) -> str:
    return re.sub(r"\{[^}]*\}", "{}", path).rstrip("/")


def main() -> int:
    ref = sys.argv[1] if len(sys.argv) > 1 else "origin/develop"
    # From where this branch left `ref`, so routes `ref` changed since are not counted; a missing ref (a shallow clone)
    # would make every route look new, so it is reported instead.
    found = subprocess.run(["git", "merge-base", ref, "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False)
    if found.returncode != 0:
        sys.stdout.write(f"base {ref} is not in this clone: fetch it (git fetch origin develop) or pass a ref\n")
        return 1
    base = found.stdout.strip()
    named = {
        shape(m) for m in re.findall(r"(/v1/[\w{}\-./*:]*|/reviews[\w{}\-./*]*|/runs[\w{}\-./*]*)", PAGE.read_text())
    }
    missing = 0
    for folder in sorted((ROOT / "services").glob("*-service")):
        new, old = load("HEAD", folder.name), load(base, folder.name)
        if not new:
            continue
        for path, item in new["paths"].items():
            if path.startswith("/health") or shape(path) in named:
                continue
            for verb in VERBS:
                op, before = item.get(verb), ((old or {}).get("paths", {}).get(path) or {}).get(verb)
                if op and (before is None or signature(new, op) != signature(old or {}, before)):
                    sys.stdout.write(f"{folder.name} {verb.upper()} {path}\n")
                    missing += 1
    sys.stdout.write(f"{missing} changed route(s) not named in {PAGE.relative_to(ROOT)}\n")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
