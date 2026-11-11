"""What an agent's write does when a team has set approvals, from the one resolver every service reads
(`effective_answer`), by failure mode: a new team's writes asking before anyone chose it; a less specific level
overriding a more specific one; an MCP write or a two-approver tool running unattended; a test account that asks (or
that ignores the team's checkbox); "ask the person" with nobody in the chat left waiting for no one; and a policy that
could not be read letting writes run.

A level is the value its policy holds: `team` is the team's `appChanges`, `app` one entry of `appChangesByApp`, `tool`
the operation's `approvalMode` and `reviewerRole`. `team=None` is a policy that could not be read; `{}` is a team that
saved nothing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

import ops_access

ASKS_PERSON = {"ask": True, "answer": "person", "reviewerRole": None, "testAccountsNeverAsk": True}
ASKS_REVIEWER = {"ask": True, "answer": "reviewer", "reviewerRole": "role_compliance", "testAccountsNeverAsk": True}
WRITE: dict[str, Any] = {"access": "write", "approvalMode": None, "reviewerRole": None, "approvers": 1}


def answer(**given: Any) -> Mapping[str, Any]:
    """The resolver's answer {waits, answer, reviewerRole, source}, with every level not given left unset."""
    levels: dict[str, Any] = {"tool": WRITE, "app": None, "team": {}, "channel": "chat", "test_account": False}
    result = ops_access.effective_answer(**{**levels, **given})
    return result if isinstance(result, Mapping) else vars(result)


def test_a_new_team_asks_nobody_before_a_write() -> None:
    got = answer()
    assert (got["waits"], got["answer"], got["source"]) == (False, "none", "team"), got


@pytest.mark.parametrize(
    ("given", "expected", "source"),
    [
        # The app's own answer beats the team's, loosening it.
        ({"team": ASKS_PERSON, "app": {"answer": "none"}}, "none", "app"),
        # And tightening it.
        ({"team": {"ask": False}, "app": {"answer": "reviewer", "reviewerRole": "role_risk"}}, "reviewer", "app"),
        # The tool's own answer beats the app's.
        (
            {"team": ASKS_REVIEWER, "app": {"answer": "none"}, "tool": {**WRITE, "approvalMode": "person"}},
            "person",
            "tool",
        ),
        # A tool with no answer of its own follows its app.
        ({"team": ASKS_PERSON, "app": {"answer": "none"}, "tool": {**WRITE, "approvalMode": None}}, "none", "app"),
    ],
)
def test_the_most_specific_level_wins(given: dict[str, Any], expected: str, source: str) -> None:
    got = answer(**given)
    assert (got["answer"], got["source"]) == (expected, source), got


def test_a_write_over_mcp_waits_whatever_the_levels_say() -> None:
    got = answer(channel="mcp", team={"ask": False}, app={"answer": "none"}, tool={**WRITE, "approvalMode": "none"})
    assert (got["waits"], got["source"]) == (True, "mcp"), got


def test_a_test_account_never_asks_while_the_checkbox_is_on_and_asks_when_it_is_off() -> None:
    on = answer(team=ASKS_REVIEWER, test_account=True)
    off = answer(team={**ASKS_REVIEWER, "testAccountsNeverAsk": False}, test_account=True)
    assert (on["waits"], on["source"], off["waits"]) == (False, "test-account", True), (on, off)


def test_a_tool_with_two_approvers_asks_a_reviewer_even_where_the_team_asks_nobody() -> None:
    got = answer(team={"ask": False}, tool={**WRITE, "approvers": 2, "reviewerRole": "role_treasury"})
    assert (got["waits"], got["answer"], got["reviewerRole"]) == (True, "reviewer", "role_treasury"), got


def test_ask_the_person_with_nobody_in_the_chat_goes_to_the_teams_reviewer_role() -> None:
    team = {**ASKS_PERSON, "reviewerRole": "role_compliance"}
    got = answer(team=team, channel="workflow")
    assert (got["waits"], got["answer"], got["reviewerRole"]) == (True, "reviewer", "role_compliance"), got


def test_a_policy_that_cannot_be_read_keeps_the_write_waiting() -> None:
    got = answer(team=None)
    assert got["waits"] is True and got["answer"] != "none", got
