"""The apps line, by failure mode: an app the install lacks, a built-in or a removed plugin is named; an app off for the
team reads as usable; the person's missing sign-in is not said, so the model asks for a token; another team's app or
another person's state reaches the line; a team with many apps grows the line past its budget; a kept line hides an
app just turned on."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.api.apps_line import KEEP_S, MAX_CHARS, AppsLine, render


def card(name: str, state: str, *, kind: str = "plugin", sign_in: str | None = "person") -> dict[str, Any]:
    return {"name": name, "kind": kind, "appState": state, "signIn": sign_in}


class Cards:
    """tools-service's app list per team, each card read for the person asking."""

    def __init__(self, by_team: dict[str, list[dict[str, Any]]]) -> None:
        self.by_team = by_team
        self.asked: list[tuple[str | None, str | None]] = []

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        self.asked.append((person, team))
        return self.by_team.get(team or "", [])


def test_on_off_and_sign_in_states_read_in_words_and_builtins_and_removed_apps_are_left_out() -> None:
    text = render(
        [
            card("Salesforce", "needs_sign_in"),
            card("Google Calendar", "not_installed"),
            card("GitHub", "connected"),
            card("Files", "connected", kind="builtin"),
            card("Old CRM", "removed"),
        ]
    )
    assert text is not None
    assert "Salesforce: on · you are not signed in (a call shows a Connect card)" in text
    assert "Google Calendar: installed, off for this team (a team admin turns it on)" in text
    assert "GitHub: on · you are signed in" in text
    assert "Files" not in text and "Old CRM" not in text


def test_a_team_with_no_app_gets_no_line() -> None:
    assert render([card("Files", "connected", kind="builtin")]) is None


async def test_the_line_is_the_asking_teams_and_persons_only() -> None:
    cards = Cards({"team_a": [card("Salesforce", "connected")], "team_b": [card("Zendesk", "connected")]})
    line = AppsLine(SimpleNamespace(app_states=cards))  # type: ignore[arg-type]
    text = await line.line("team_a", "dana@bank.example", now=0)
    assert text is not None and "Salesforce" in text and "Zendesk" not in text
    assert cards.asked == [("dana@bank.example", "team_a")]


def test_many_apps_stay_within_the_budget_and_count_the_rest() -> None:
    text = render([card(f"App number {i:02d}", "connected") for i in range(30)])
    assert text is not None and len(text) <= MAX_CHARS, len(text or "")
    assert text.endswith("more; ask about one by name")


async def test_a_kept_line_is_read_again_once_the_team_turns_an_app_on() -> None:
    cards = Cards({"team_a": [card("Salesforce", "not_installed")]})
    line = AppsLine(SimpleNamespace(app_states=cards))  # type: ignore[arg-type]
    await line.line("team_a", "dana@bank.example", now=0)
    cards.by_team["team_a"] = [card("Salesforce", "needs_sign_in")]
    assert "off for this team" in (await line.line("team_a", "dana@bank.example", now=1) or "")
    line.forget("team_a")
    assert "not signed in" in (await line.line("team_a", "dana@bank.example", now=2) or "")
    assert "not signed in" in (await line.line("team_a", "dana@bank.example", now=2 + KEEP_S + 1) or "")
