"""The core content pack ships built in, by failure mode: the pack is missing from builtin-plugins/ or not among the
folders a stack loads, so no stack has it and its case and task types still come from first-read seeding."""

from __future__ import annotations

from pathlib import Path

import yaml

from ops_service_kit.settings import Settings

CORE = Path(__file__).resolve().parents[2] / "builtin-plugins" / "ops_plugin_core"


def test_every_stack_loads_the_core_pack_with_its_case_and_task_types(tmp_path: Path) -> None:
    assert yaml.safe_load((CORE / "plugin.yaml").read_text())["id"] == "opsai.core"
    assert list((CORE / "templates" / "case-types").glob("*.yaml"))
    assert list((CORE / "templates" / "task-types").glob("*.yaml"))
    # An install that added no plugin of its own still loads the built-in core pack.
    assert str(CORE) in Settings(plugins_dir=tmp_path, plugin_paths=[]).plugin_folders
