"""A plugin write that says nothing about approval: the operation agents call runs at once, as every other write with
no setting does; a manifest's ask-first flag is not stored as the tool's answer, so the app and team decide."""

from __future__ import annotations

from pathlib import Path

from ops_plugin_sdk.loader import discover
from ops_plugin_sdk.manifest import Tool
from ops_tools.plugins.host import operation_of

DESK = Path(__file__).parent / "plugin_fields" / "fields_desk"


def test_a_plugin_write_is_stored_without_a_wait_whatever_its_manifest_flag_says() -> None:
    loaded = next(p for p in discover([], [str(DESK)]) if p.plugin is not None)
    assert loaded.plugin is not None
    m = loaded.plugin.manifest
    base = m.tools[0].model_dump(exclude_defaults=True, exclude={"requires_approval"})
    silent = Tool.model_validate({**base, "access": "write"})
    asks_first = Tool.model_validate({**base, "access": "write", "requires_approval": True})
    read = Tool.model_validate({**base, "access": "read"})
    assert operation_of(m, silent, "op_1")["requires_approval"] is False
    assert operation_of(m, asks_first, "op_1")["requires_approval"] is False
    assert operation_of(m, read, "op_1")["requires_approval"] is False
