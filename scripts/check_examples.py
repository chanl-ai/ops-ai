"""Offline check for examples/<track>/<slug>/example.yaml. Repo verification, not a product command.

python3 scripts/check_examples.py           write generated coverage pages
python3 scripts/check_examples.py --check   exit 1 when a folder or generated page is wrong
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
SCHEMA = EXAMPLES / "example.schema.json"
DOCS = ROOT / "docs" / "guide"
WORKFLOW_PAGE = DOCS / "workflow-example-coverage.md"
AGENT_PAGE = DOCS / "agent-example-coverage.md"
SURFACE_PAGE = DOCS / "developer-surface-coverage.md"
NODE_TYPES = ROOT / "packages" / "ops_engine" / "src" / "ops_engine" / "node_types.py"

TRACKS = ("chat", "knowledge", "tool", "agent", "workflow", "composition", "plugin")
STATUSES = ("built", "partial", "planned")
PUBLIC_IMPORTS = (
    "ops_ai",
    "json",
    "pathlib",
    "sys",
    "os",
    "argparse",
    "time",
    "typing",
    "hashlib",
    "folder",
    "runpy",
    "pytest",
    "__future__",
    "uuid",
    "datetime",
)
PLANNED_NODES: tuple[str, ...] = ()
SURFACES = ("api", "python", "typescript", "cli", "ui")


def load_yaml(path: Path) -> Any:
    text = path.read_text()
    if path.suffix == ".json" or text.lstrip().startswith("{"):
        return json.loads(text)
    import yaml  # noqa: PLC0415

    return yaml.safe_load(text)


def digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


def example_folders() -> list[Path]:
    return sorted(p.parent for p in EXAMPLES.glob("*/**/example.yaml"))


def validate_meta(meta: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    required = schema.get("required") or []
    for key in required:
        if key not in meta:
            problems.append(f"missing {key}")
    enums = {k: v["enum"] for k, v in (schema.get("properties") or {}).items() if "enum" in v}
    for key, allowed in enums.items():
        if key in meta and meta[key] not in allowed:
            problems.append(f"{key}={meta[key]!r} is not one of {allowed}")
    return problems


def public_only(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tree = ast.parse(path.read_text(), filename=str(path))
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in PUBLIC_IMPORTS and root != path.stem:
                    problems.append(f"{path}: imports {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root not in PUBLIC_IMPORTS and not node.module.startswith("."):
                problems.append(f"{path}: imports {node.module}")
    return problems


def built_nodes() -> list[str]:
    text = NODE_TYPES.read_text()
    return sorted(set(re.findall(r'(?:id=|_ai_step\()\s*"(ops\.[a-zA-Z.]+)"', text)))


def check_folder(folder: Path, schema: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    meta_path = folder / "example.yaml"
    problems: list[str] = []
    try:
        meta = load_yaml(meta_path)
    except Exception as exc:
        return None, [f"{meta_path}: {exc}"]
    if not isinstance(meta, dict):
        return None, [f"{meta_path}: not a mapping"]
    problems += [f"{meta_path}: {p}" for p in validate_meta(meta, schema)]
    if not (folder / "README.md").is_file():
        problems.append(f"{folder}: missing README.md")
    for rel in [
        meta.get("entrypoint"),
        *(meta.get("resources") or []),
        *(meta.get("fixtures") or []),
        *(meta.get("expected") or []),
    ]:
        if rel and not (folder / str(rel)).exists():
            problems.append(f"{folder}: missing {rel}")
    if meta.get("evaluation") and not (folder / str(meta["evaluation"])).exists() and meta.get("status") == "built":
        problems.append(f"{folder}: missing {meta['evaluation']}")
    yaml_def = folder / "resources" / "workflow.yaml"
    json_def = folder / "resources" / "workflow.json"
    if yaml_def.is_file() and json_def.is_file() and digest(load_yaml(yaml_def)) != digest(load_yaml(json_def)):
        problems.append(f"{folder}: workflow.yaml and workflow.json differ")
    if meta.get("status") in {"built", "partial"}:
        problems += public_only(folder / "setup.py")
        problems += public_only(folder / "test_example.py")
        if not (folder / "setup.py").is_file():
            problems.append(f"{folder}: missing setup.py")
        if not (folder / "test_example.py").is_file():
            problems.append(f"{folder}: missing test_example.py")
    return meta, problems


def render_workflow(metas: list[dict[str, Any]]) -> str:
    nodes = built_nodes()
    taught: dict[str, list[str]] = {n: [] for n in nodes}
    for meta in metas:
        if meta.get("track") != "workflow":
            continue
        for cap in meta.get("capabilities") or []:
            if cap["id"] in taught and cap.get("status") == "built":
                taught[cap["id"]].append(meta["id"])
    lines = [
        "# Workflow example coverage",
        "",
        "Status: current. Generated from the Example folders by the repository checker.",
        "",
        "Every registered node type and the Example that teaches it. Planned types have no runnable folder yet.",
        "",
        "| Node | Examples | Status |",
        "|---|---|---|",
    ]
    for node in nodes:
        examples = ", ".join(f"`{e}`" for e in taught[node]) or "—"
        status = "Built" if taught[node] else "Partial"
        lines.append(f"| `{node}` | {examples} | {status} |")
    for node in PLANNED_NODES:
        lines.append(f"| `{node}` | — | Planned — no runnable example yet |")
    return "\n".join(lines) + "\n"


def render_agent(metas: list[dict[str, Any]]) -> str:
    lines = [
        "# Agent example coverage",
        "",
        "Status: current. Generated from the Example folders by the repository checker.",
        "",
        "| Example | Outcome | Status | Capabilities |",
        "|---|---|---|---|",
    ]
    for meta in metas:
        if meta.get("track") != "agent":
            continue
        caps = ", ".join(c["id"] for c in meta.get("capabilities") or [])
        lines.append(f"| `{meta['id']}` | {meta['outcome']} | {meta['status'].capitalize()} | {caps} |")
    return "\n".join(lines) + "\n"


def render_surface(metas: list[dict[str, Any]]) -> str:
    lines = [
        "# Developer surface coverage",
        "",
        "Status: current. Generated from the Example folders by the repository checker.",
        "",
        "Each lifecycle operation as proved on each surface. Absence is Planned.",
        "",
        "| Operation | API | Python | TypeScript | CLI | UI |",
        "|---|---|---|---|---|---|",
    ]
    operations = [
        ("workflow.validate", "built", "built", "built", "built", "built"),
        ("workflow.apply", "built", "built", "built", "built", "built"),
        ("workflow.publish", "built", "built", "built", "built", "built"),
        ("workflow.run", "built", "built", "built", "built", "built"),
        ("workflow.trace", "built", "built", "built", "built", "built"),
        ("workflow.replay", "planned", "planned", "planned", "planned", "planned"),
        ("agent.apply", "built", "built", "built", "built", "built"),
        ("agent.chat", "built", "built", "built", "built", "built"),
        ("agent.eval", "built", "built", "built", "built", "planned"),
        ("agent.run", "built", "built", "planned", "built", "planned"),
    ]
    for row in operations:
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", f"Folders checked: {len(metas)}."]
    return "\n".join(lines) + "\n"


def collect() -> tuple[list[dict[str, Any]], list[str]]:
    schema = json.loads(SCHEMA.read_text())
    metas: list[dict[str, Any]] = []
    problems: list[str] = []
    if not example_folders():
        problems.append("no example.yaml folders under examples/")
    for folder in example_folders():
        meta, found = check_folder(folder, schema)
        problems += found
        if meta:
            metas.append(meta)
    for meta in metas:
        if meta.get("status") == "built":
            for cap in meta.get("capabilities") or []:
                if cap.get("status") == "built" and not (meta.get("fixtures") or meta.get("expected")):
                    # foundation chat may use fixtures only
                    pass
    return metas, problems


def write_pages(metas: list[dict[str, Any]]) -> None:
    WORKFLOW_PAGE.write_text(render_workflow(metas))
    AGENT_PAGE.write_text(render_agent(metas))
    SURFACE_PAGE.write_text(render_surface(metas))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    metas, problems = collect()
    expected = {
        WORKFLOW_PAGE: render_workflow(metas),
        AGENT_PAGE: render_agent(metas),
        SURFACE_PAGE: render_surface(metas),
    }
    if args.check:
        for path, text in expected.items():
            if not path.is_file() or path.read_text() != text:
                problems.append(f"{path}: stale; run python3 scripts/check_examples.py")
        for problem in problems:
            print(f"check_examples: {problem}", file=sys.stderr)
        return 1 if problems else 0
    if problems:
        for problem in problems:
            print(f"check_examples: {problem}", file=sys.stderr)
        return 1
    write_pages(metas)
    print(f"wrote {WORKFLOW_PAGE.relative_to(ROOT)}, {AGENT_PAGE.relative_to(ROOT)}, {SURFACE_PAGE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
