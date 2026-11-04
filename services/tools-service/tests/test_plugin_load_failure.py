"""A plugin that fails to load, by failure mode: it is dropped with nothing said, so the install's admin never learns
why its tools are missing."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ops_tools.plugins.host import PluginHost
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings


def test_a_plugin_that_fails_to_load_is_logged_with_why(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    broken = tmp_path / "broken_plugin"
    broken.mkdir()
    (broken / "__init__.py").write_text("raise RuntimeError('missing manifest')\n")
    caplog.set_level(logging.WARNING)
    host = PluginHost.start(ModuleStore(None), PluginBindings(None), {}, [str(broken)])  # type: ignore[arg-type]
    assert not host.plugins
    assert "plugin_failed" in caplog.text and "missing manifest" in caplog.text, caplog.text
