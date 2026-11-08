"""A plugin tool's declared result shape, by failure mode: the manifest's `shape` never reaches the operation agents
read, so chat infers the shape instead of drawing what the plugin declared."""

from __future__ import annotations

from pathlib import Path

from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.manifest import Tool
from ops_tools.plugins.host import operation_of

DESK = Path(__file__).parent / "plugin_fields" / "fields_desk"


def test_a_tools_declared_shape_is_its_operations_output_shape() -> None:
    loaded = next(p for p in discover([], [str(DESK)]) if p.plugin is not None)
    assert loaded.plugin is not None
    m = loaded.plugin.manifest
    tool = m.tools[0]
    declared = Tool.model_validate({**tool.model_dump(exclude_defaults=True), "shape": "rows"})
    assert operation_of(m, declared, "op_1")["output_shape"] == "rows"
    assert operation_of(m, tool, "op_1")["output_shape"] is None
