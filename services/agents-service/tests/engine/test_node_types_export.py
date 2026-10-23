"""The console's copy of the node types (c-486) matches the registry: a port added or removed without re-running
scripts/export_node_types.py would leave the seed bake and the layout tests placing the wrong ports."""

from __future__ import annotations

import importlib.util
from pathlib import Path


def test_the_console_node_types_match_the_registry() -> None:
    script = Path(__file__).parents[2] / "scripts" / "export_node_types.py"
    spec = importlib.util.spec_from_file_location("export_node_types", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.TARGET.read_text() == module.exported(), (
        "node-types.json is stale: run `uv run python scripts/export_node_types.py` in services/agents-service"
    )
