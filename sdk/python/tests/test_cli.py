"""The `ops` command, by failure mode: an area it does not know runs anything, `ops plugin` without the plugin kit
fails with a traceback in place of what to install, and `ops plugin` loses the verb or the folder on the way to the
kit."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest
from ops_ai.cli import main


def test_an_unknown_area_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        main(["nothing"])
    assert stop.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_ops_plugin_without_the_kit_says_what_to_install(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # None in sys.modules makes the import fail as it does where the kit is not installed.
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk.cli", None)
    assert main(["plugin", "validate", "somewhere"]) == 2
    assert "install ops-ai[plugin]" in capsys.readouterr().err


def test_ops_plugin_hands_the_verb_and_folder_to_the_kit(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []
    kit = types.ModuleType("ops_plugin_sdk.cli")
    kit.main = lambda argv: seen.append(argv) or 1  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk", types.ModuleType("ops_plugin_sdk"))
    monkeypatch.setitem(sys.modules, "ops_plugin_sdk.cli", kit)
    assert main(["plugin", "test", "plugins/desk"]) == 1
    assert seen == [["plugin", "test", "plugins/desk"]]
