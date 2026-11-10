"""The account a workflow step's call uses when the run already chose one (an agent started it): the step wins."""

from __future__ import annotations

from ops_agents.api.engine_host import merged_accounts

SF, GH = "plugin:opsai.salesforce", "plugin:opsai.github"


def test_a_step_naming_an_account_wins_over_the_agent_that_started_the_run() -> None:
    """Failure mode: the agent's account is used for a step that names another (uc-696 step 2 drives this end to end
    once an agent-started run can act for its person)."""
    got = merged_accounts({SF: "EU org", GH: "Platform org"}, {SF: "Retail org"})
    assert got == {SF: "Retail org", GH: "Platform org"}


def test_a_team_account_call_keeps_only_the_steps_choice() -> None:
    """Failure mode: a person's own pick from their chat travels into a call run as the team account (N1)."""
    assert merged_accounts({GH: "Mobile org · Maya"}, {SF: "Retail org"}, team_account=True) == {SF: "Retail org"}
