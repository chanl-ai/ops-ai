"""A plugin write that says nothing about approval follows its app and team; one whose manifest says ask first stores
that as the tool's own default answer (a reviewer's approval), which an admin's tool setting can still change."""

from __future__ import annotations

from pathlib import Path

from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.manifest import Tool
from ops_tools.plugins.host import operation_of

DESK = Path(__file__).parent / "plugin_fields" / "fields_desk"


def test_a_plugins_ask_first_flag_becomes_the_tools_default_approval_mode() -> None:
    loaded = next(p for p in discover([], [str(DESK)]) if p.plugin is not None)
    assert loaded.plugin is not None
    m = loaded.plugin.manifest
    base = m.tools[0].model_dump(exclude_defaults=True, exclude={"requires_approval"})
    silent = Tool.model_validate({**base, "access": "write"})
    asks_first = Tool.model_validate({**base, "access": "write", "requires_approval": True})
    read = Tool.model_validate({**base, "access": "read"})
    assert operation_of(m, silent, "op_1")["approval_mode"] is None
    assert operation_of(m, asks_first, "op_1")["approval_mode"] == "reviewer"
    assert operation_of(m, read, "op_1")["approval_mode"] is None
