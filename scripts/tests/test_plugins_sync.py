"""plugins-sync by failure mode: hand copies in the plugins folder are lost, a second run piles up backups, and a pin
that can move reaches the image."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC = ROOT / "scripts" / "plugins_sync.sh"


def _run(target: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SYNC), str(target)], capture_output=True, text=True, check=False, env={**os.environ, **env}
    )


def test_hand_copies_are_moved_aside_not_deleted(tmp_path: Path) -> None:
    dev = tmp_path / "ops-ai-plugins" / "plugins" / "demo"
    dev.mkdir(parents=True)
    plugins = tmp_path / "plugins"
    (plugins / "ops_plugin_hand").mkdir(parents=True)
    (plugins / "ops_plugin_hand" / "plugin.yaml").write_text("id: hand\n")
    (plugins / "README.md").write_text("kept\n")

    # PLUGINS_DEV keeps the run offline while exercising the same backup step as the pinned path.
    out = _run(plugins, PLUGINS_DEV=str(tmp_path / "ops-ai-plugins"))
    assert out.returncode == 0, out.stderr
    backups = list(tmp_path.glob("plugins.bak-*"))
    assert len(backups) == 1 and (backups[0] / "ops_plugin_hand" / "plugin.yaml").read_text() == "id: hand\n"
    assert (plugins / "README.md").read_text() == "kept\n"
    assert (plugins / "demo").is_symlink()

    # A second run replaces what the first one put there and makes no second backup.
    assert _run(plugins, PLUGINS_DEV=str(tmp_path / "ops-ai-plugins")).returncode == 0
    assert len(list(tmp_path.glob("plugins.bak-*"))) == 1


def test_every_pin_is_a_full_commit() -> None:
    # The plugins Ops AI ships are built in (builtin-plugins/); the pins name only outside plugins an install adds.
    pins = json.loads((ROOT / "deploy" / "plugins.json").read_text())["plugins"]
    assert all(re.fullmatch(r"[0-9a-f]{40}", p["ref"]) for p in pins)
