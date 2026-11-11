"""Whether a tool write waits for a person's approval, from the one rule every service resolves it by."""

from __future__ import annotations

import pytest

from ops_access import write_waits


@pytest.mark.parametrize(
    ("access", "setting", "waits"),
    [
        # A write that says nothing about approval runs at once: the team's "ask before changes" switch, off by
        # default, is what makes it wait.
        ("write", None, False),
        # A tool a team switched to ask first waits.
        ("write", True, True),
        ("write", False, False),
        # A read never waits, whatever it carries.
        ("read", None, False),
        ("read", True, False),
    ],
)
def test_a_write_waits_only_when_its_setting_says_so(access: str, setting: bool | None, waits: bool) -> None:
    assert write_waits(access, setting) is waits
