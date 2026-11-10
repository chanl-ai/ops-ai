"""The account each app's call uses, from one rule: a step's choice over a chat's over an agent's."""

from __future__ import annotations

from ops_agents.domain.accounts import chosen_accounts

SF, GH, JR = "plugin:opsai.salesforce", "plugin:opsai.github", "plugin:opsai.jira"


def test_a_step_wins_over_the_chat_and_the_chat_over_the_agent() -> None:
    """Failure mode: the agent's account is used for a step or a chat that names another (uc-696 drives the step end
    to end, uc-697 the chat)."""
    got = chosen_accounts(
        agent={SF: "EU org", GH: "Platform org", JR: "Ops site"},
        chat={SF: "US org", GH: "Mobile org"},
        step={SF: "Retail org"},
    )
    assert got == {SF: "Retail org", GH: "Mobile org", JR: "Ops site"}


def test_a_team_account_call_keeps_only_the_steps_choice() -> None:
    """Failure mode: a person's own pick from their chat travels into a call run as the team account."""
    got = chosen_accounts(agent={JR: "Ops site"}, chat={GH: "Mobile org"}, step={SF: "Retail org"}, team_account=True)
    assert got == {SF: "Retail org"}


def test_a_blank_choice_falls_through_to_the_layer_below() -> None:
    """Failure mode: a chat that cleared its pick sends an empty name, and the call is refused instead of using the
    agent's account."""
    assert chosen_accounts(agent={SF: "EU org"}, chat={SF: "  "}) == {SF: "EU org"}
