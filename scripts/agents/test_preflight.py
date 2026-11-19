"""One test per preflight refusal, plus one pass, through the real check()."""

from datetime import UTC, datetime

import preflight


def card(**over):
    base = {
        "id": "c-1",
        "holder": "builder-c-1",
        "plan": {"files": ["a.py"], "scope": "Design: docs/plans/x/design.html"},
        "events": [
            {"action": "plan", "at": "2026-11-01T00:00:00Z"},
            {"action": "approve", "at": "2026-11-02T00:00:00Z"},
        ],
    }
    base.update(over)
    return base


def at(day):
    return datetime(2026, 11, day, tzinfo=UTC)


def test_refuses_when_not_claimed_by_running_agent():
    line = preflight.check(card(holder="someone-else"), "builder-c-1", lambda p: None)
    assert "not claimed by builder-c-1" in line and "\n" not in line


def test_refuses_without_file_list():
    c = card(plan={"files": [], "scope": ""})
    assert "no file list" in preflight.check(c, "builder-c-1", lambda p: None)


def test_refuses_when_design_changed_after_approval():
    line = preflight.check(card(), "builder-c-1", lambda p: at(5))
    assert "docs/plans/x/design.html changed" in line


def test_passes_when_claimed_listed_and_design_unchanged():
    assert preflight.check(card(), "builder-c-1", lambda p: at(1)) is None
