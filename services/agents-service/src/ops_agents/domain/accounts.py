"""Which account of each app a call uses. Steps, chats and agents each choose an account per app (app id to account
name); this module is the one place that decides which choice wins, so the run context, the chat's picker and the
prompt's apps line all name the same account. tools-service checks the chosen name on every call (plugins/host.py
for_call).
"""

from __future__ import annotations

from collections.abc import Mapping


def chosen_accounts(
    agent: Mapping[str, str] | None = None,
    chat: Mapping[str, str] | None = None,
    step: Mapping[str, str] | None = None,
    *,
    team_account: bool = False,
) -> dict[str, str]:
    """Return the account each app's calls use: the step's choice over the chat's over the agent's.

    A layer may already be a choice made further out: a workflow run started from a chat carries that chat's (and its
    agent's) choice, passed here as `agent` or `chat` by the caller. A blank name is no choice, so the layer below
    applies.

    Args:
        agent: The agent's own account per app.
        chat: The chat's pick per app, or the choice of the run that started this one.
        step: A workflow step's account per app.
        team_account: The call runs on the team's account in place of a person's; it acts for nobody, so a person's
            own pick from their chat or agent never travels into it and only the step's choice is kept.
    """
    layers = (step,) if team_account else (agent, chat, step)
    out: dict[str, str] = {}
    for layer in layers:
        for app, name in (layer or {}).items():
            if name and name.strip():
                out[str(app)] = name.strip()
    return out
