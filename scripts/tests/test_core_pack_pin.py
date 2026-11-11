"""The core content pack is pinned in deploy/plugins.json, by failure mode: the pack is built in the plugins
repository but never pinned, so no stack installs it and its case and task types still come from first-read seeding;
and the pin names a branch or a hash that does not identify one file set."""

from __future__ import annotations

import json
import re
from pathlib import Path

PINS = Path(__file__).resolve().parents[2] / "deploy" / "plugins.json"


def test_the_core_pack_is_pinned_to_one_commit_and_one_hash() -> None:
    pins = [p for p in json.loads(PINS.read_text())["plugins"] if p["path"] == "plugins/core"]
    assert len(pins) == 1, "deploy/plugins.json must pin plugins/core once"
    assert re.fullmatch(r"[0-9a-f]{40}", pins[0]["ref"]) and re.fullmatch(r"[0-9a-f]{64}", pins[0]["sha256"])
