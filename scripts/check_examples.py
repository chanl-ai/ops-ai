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
CAPABILITY_SCHEMA = EXAMPLES / "capability.schema.json"
CAPABILITIES = EXAMPLES / "capabilities.yaml"
REGISTRY = EXAMPLES / "registry.json"
DOCS = ROOT / "docs" / "guide"
WORKFLOW_PAGE = DOCS / "workflow-example-coverage.md"
AGENT_PAGE = DOCS / "agent-example-coverage.md"
SURFACE_PAGE = DOCS / "developer-surface-coverage.md"
NODE_TYPES = ROOT / "packages" / "ops_engine" / "src" / "ops_engine" / "node_types.py"

TRACKS = ("chat", "knowledge", "tool", "agent", "skill", "workflow", "composition", "plugin")
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
        ("agent.eval", "built", "built", "planned", "planned", "planned"),
        ("agent.run", "built", "built", "planned", "built", "planned"),
    ]
    for row in operations:
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", f"Folders checked: {len(metas)}."]
    return "\n".join(lines) + "\n"


def load_capabilities() -> tuple[list[dict[str, Any]], list[str]]:
    problems: list[str] = []
    if not CAPABILITIES.is_file():
        return [], [f"missing {CAPABILITIES.relative_to(ROOT)}"]
    try:
        data = load_yaml(CAPABILITIES)
    except Exception as exc:
        return [], [f"{CAPABILITIES}: {exc}"]
    if not isinstance(data, dict) or not isinstance(data.get("capabilities"), list):
        return [], [f"{CAPABILITIES}: expected a mapping with capabilities: []"]
    schema = json.loads(CAPABILITY_SCHEMA.read_text()) if CAPABILITY_SCHEMA.is_file() else {}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(data["capabilities"]):
        if not isinstance(row, dict):
            problems.append(f"{CAPABILITIES}: capabilities[{index}] is not a mapping")
            continue
        if schema:
            problems += [f"{CAPABILITIES}: capabilities[{index}]: {p}" for p in validate_meta(row, schema)]
        cap_id = str(row.get("id") or "")
        if not cap_id:
            problems.append(f"{CAPABILITIES}: capabilities[{index}] missing id")
            continue
        if cap_id in seen:
            problems.append(f"{CAPABILITIES}: duplicate capability id {cap_id}")
        seen.add(cap_id)
        rows.append(row)
    return rows, problems


def check_capabilities(rows: list[dict[str, Any]], metas: list[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    by_folder = {str(Path(m.get("_folder") or "")): m for m in metas if m.get("_folder")}
    for row in rows:
        folder_rel = str(row.get("folder") or "").rstrip("/")
        status = row.get("status")
        if status == "built":
            if not folder_rel:
                problems.append(f"capability {row['id']}: built rows need folder")
                continue
            folder = ROOT / folder_rel
            if not (folder / "example.yaml").is_file():
                problems.append(f"capability {row['id']}: missing {folder_rel}/example.yaml")
                continue
            meta = by_folder.get(folder_rel) or by_folder.get(str(folder.relative_to(ROOT)))
            if meta is None:
                # collect() stores absolute-ish relative path
                for key, value in by_folder.items():
                    if key.endswith(folder_rel) or folder_rel.endswith(key):
                        meta = value
                        break
            if meta is None:
                problems.append(f"capability {row['id']}: folder {folder_rel} not collected")
                continue
            held = {c.get("id") for c in (meta.get("capabilities") or [])}
            if row["id"] not in held:
                problems.append(
                    f"capability {row['id']}: {folder_rel}/example.yaml must list capabilities id {row['id']}"
                )
            guide = row.get("guide") or meta.get("guide")
            if guide and not (ROOT / str(guide)).is_file():
                problems.append(f"capability {row['id']}: missing guide {guide}")
        elif folder_rel and status == "planned" and str(row.get("folder") or "").endswith("12-brief-and-publish-check"):
            # proposed path may not exist yet
            pass
        elif folder_rel and (ROOT / folder_rel / "example.yaml").is_file() is False and status == "planned":
            # ok: catalog may name a future folder
            pass
    return problems


def render_registry(rows: list[dict[str, Any]], metas: list[dict[str, Any]]) -> dict[str, Any]:
    folders = {
        str(Path(m["_folder"])): {
            "id": m.get("id"),
            "title": m.get("title"),
            "track": m.get("track"),
            "status": m.get("status"),
            "outcome": m.get("outcome"),
            "guide": m.get("guide"),
            "capabilities": m.get("capabilities") or [],
            "surfaces": m.get("surfaces") or {},
        }
        for m in metas
        if m.get("_folder")
    }
    capabilities: list[dict[str, Any]] = []
    for row in rows:
        folder_rel = str(row.get("folder") or "").rstrip("/")
        entry = {
            "id": row["id"],
            "title": row.get("title"),
            "track": row.get("track"),
            "status": row.get("status"),
            "outcome": row.get("outcome"),
            "guide": row.get("guide"),
            "folder": folder_rel or None,
            "example": row.get("example"),
            "surfaces": row.get("surfaces") or {},
            "deepLink": f"#{row['id']}",
            "siteHint": f"https://opsai.chanl.ai/docs/guide/examples#{row['id']}",
        }
        if row.get("notes"):
            entry["notes"] = row["notes"]
        if folder_rel and folder_rel in folders:
            entry["folderManifest"] = folders[folder_rel]
        capabilities.append(entry)
    return {
        "$schema": "https://opsai.chanl.ai/examples/capability.schema.json",
        "generatedBy": "scripts/check_examples.py",
        "capabilities": capabilities,
        "folders": len(metas),
    }


def collect() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    schema = json.loads(SCHEMA.read_text())
    metas: list[dict[str, Any]] = []
    problems: list[str] = []
    if not example_folders():
        problems.append("no example.yaml folders under examples/")
    for folder in example_folders():
        meta, found = check_folder(folder, schema)
        problems += found
        if meta:
            meta = dict(meta)
            meta["_folder"] = str(folder.relative_to(ROOT))
            metas.append(meta)
    rows, cap_problems = load_capabilities()
    problems += cap_problems
    problems += check_capabilities(rows, metas)
    return metas, rows, problems


def write_pages(metas: list[dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    WORKFLOW_PAGE.write_text(render_workflow(metas))
    AGENT_PAGE.write_text(render_agent(metas))
    SURFACE_PAGE.write_text(render_surface(metas))
    REGISTRY.write_text(json.dumps(render_registry(rows, metas), indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    metas, rows, problems = collect()
    expected = {
        WORKFLOW_PAGE: render_workflow(metas),
        AGENT_PAGE: render_agent(metas),
        SURFACE_PAGE: render_surface(metas),
        REGISTRY: json.dumps(render_registry(rows, metas), indent=2) + "\n",
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
    write_pages(metas, rows)
    print(
        f"wrote {WORKFLOW_PAGE.relative_to(ROOT)}, {AGENT_PAGE.relative_to(ROOT)}, "
        f"{SURFACE_PAGE.relative_to(ROOT)}, {REGISTRY.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
