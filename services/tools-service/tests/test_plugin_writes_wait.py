"""A plugin write that says nothing about approval: the operation agents call must wait for a person, as every other
write with no setting does, and a plugin that marks a write to run at once keeps that."""

from __future__ import annotations

from pathlib import Path

from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.manifest import Tool
from ops_tools.plugins.host import operation_of

DESK = Path(__file__).parent / "plugin_fields" / "fields_desk"


def test_a_plugin_write_with_no_approval_setting_waits_and_one_marked_to_run_at_once_runs() -> None:
    loaded = next(p for p in discover([], [str(DESK)]) if p.plugin is not None)
    assert loaded.plugin is not None
    m = loaded.plugin.manifest
    base = m.tools[0].model_dump(exclude_defaults=True, exclude={"requires_approval"})
    silent = Tool.model_validate({**base, "access": "write"})
    at_once = Tool.model_validate({**base, "access": "write", "requires_approval": False})
    read = Tool.model_validate({**base, "access": "read"})
    assert operation_of(m, silent, "op_1")["requires_approval"] is True
    assert operation_of(m, at_once, "op_1")["requires_approval"] is False
    assert operation_of(m, read, "op_1")["requires_approval"] is False
