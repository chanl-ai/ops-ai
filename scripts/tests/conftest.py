"""Every script test runs without the release script's controls in the environment: the release intake runs these
tests through ci-local with its own RESUME, TRAIN or INTAKE_DIR set, and release.py in a fixture repository would
read them and refuse."""

from __future__ import annotations

import pytest

RELEASE_CONTROLS = ("TRAIN", "PRS", "DRY", "RESUME", "RERUN", "REPORT", "INTAKE_DIR", "INTAKE_SETUP", "BRANCH", "FROM")
RELEASE_CONTROLS += ("HOTFIX", "V")


@pytest.fixture(autouse=True)
def _no_release_controls(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in RELEASE_CONTROLS:
        monkeypatch.delenv(name, raising=False)
