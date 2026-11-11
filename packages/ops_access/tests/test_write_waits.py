"""Whether a tool write waits for a person's approval, from the one rule every service resolves it by."""

from __future__ import annotations

import pytest

from ops_access import write_waits


@pytest.mark.parametrize(
    ("access", "setting", "waits"),
    [
        # A write that says nothing about approval waits: a tool must say it runs at once.
        ("write", None, True),
        ("write", True, True),
        # A team that switched a tool to run at once keeps that setting.
        ("write", False, False),
        # A read never waits, whatever it carries.
        ("read", None, False),
        ("read", True, False),
    ],
)
def test_a_write_waits_unless_its_setting_says_it_runs_at_once(access: str, setting: bool | None, waits: bool) -> None:
    assert write_waits(access, setting) is waits
