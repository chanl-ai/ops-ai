"""kb-service reaches files only through files-service's client (c-094): importing files-service's own code
(`ops_files`) would couple kb-service to its tables and storage, and a second copy of its upload logic would drift."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ops_kb"


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_kb_service_never_imports_files_service_code() -> None:
    found = [
        f"{path.relative_to(SRC.parent)}: {name}"
        for path in sorted(SRC.rglob("*.py"))
        for name in _imports(path)
        if name == "ops_files" or name.startswith("ops_files.")
    ]
    assert found == [], found
