"""agents-service never imports another service's code at runtime; it reaches tools-service over HTTP. A failure here
names the file that started reaching across."""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[2] / "src"
OTHER_SERVICES = {"ops_tools", "ops_models", "ops_files", "ops_platform"}


def test_agents_service_imports_no_other_service() -> None:
    crossings: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )
            crossings += [f"{path.relative_to(SRC)}: {n}" for n in names if n.split(".")[0] in OTHER_SERVICES]
    assert crossings == []
