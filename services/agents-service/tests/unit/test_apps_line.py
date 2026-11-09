"""The apps line, by failure mode: an app the install lacks, a built-in or a removed plugin is named; an app off for the
team reads as usable; the person's missing sign-in is not said, so the model asks for a token; another team's app or
another person's state reaches the line; a team with many apps grows the line past its budget; a kept line hides an
app just turned on."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agent_kernel.types import AgentSettings, PromptFragment, Skill
from ops_agents.api.apps_line import KEEP_S, MAX_CHARS, AppsLine, render
from ops_agents.graphs.common import with_apps


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
            card("Google Calendar", "off"),
            card("GitHub", "connected"),
            card("Files", "connected", kind="builtin"),
            card("Old CRM", "removed"),
            card("Never installed", "not_installed"),
            card("GitLab", "needs_auth_config"),
        ]
    )
    assert text is not None
    assert "Salesforce: on · you are not signed in (a call shows a Connect card)" in text
    assert "Google Calendar: installed, off for this team (a team admin turns it on)" in text
    assert "GitHub: on · you are signed in" in text
    assert "GitLab: has no auth config to sign in with (a team admin adds one)" in text
    assert "Never installed" not in text
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
    cards = Cards({"team_a": [card("Salesforce", "off")]})
    line = AppsLine(SimpleNamespace(app_states=cards))  # type: ignore[arg-type]
    await line.line("team_a", "dana@bank.example", now=0)
    cards.by_team["team_a"] = [card("Salesforce", "needs_sign_in")]
    assert "off for this team" in (await line.line("team_a", "dana@bank.example", now=1) or "")
    line.forget("team_a")
    assert "not signed in" in (await line.line("team_a", "dana@bank.example", now=2) or "")
    assert "not signed in" in (await line.line("team_a", "dana@bank.example", now=2 + KEEP_S + 1) or "")


class Ops:
    async def operations(self) -> list[Any]:
        return [
            SimpleNamespace(name="salesforce_query", module_id="mod_sf"),
            SimpleNamespace(name="read_file", module_id=None),
        ]


async def test_a_skill_says_which_app_it_needs_and_whether_the_person_is_signed_in() -> None:
    # The model loaded a Salesforce skill and called its tools with no idea the person had never signed in.
    sf = {**card("Salesforce", "needs_sign_in"), "moduleIds": ["mod_sf"]}
    agent = SimpleNamespace(
        skills=[
            SimpleNamespace(skill_id="sk_clients", tool_ids=["salesforce_query"]),
            SimpleNamespace(skill_id="sk_files", tool_ids=["read_file"]),
        ]
    )
    rt = SimpleNamespace(
        app_states=Cards({"team_a": [sf]}),
        catalog=SimpleNamespace(agent_in_flight=lambda _id: agent),  # pyright: ignore[reportUnknownLambdaType]
        directory=Ops,
    )
    line = AppsLine(rt)  # type: ignore[arg-type]

    async def turn(_agent: str) -> tuple[str, str]:
        return "team_a", "dana@bank.example"

    line._turn = turn  # type: ignore[method-assign]  # pyright: ignore[reportPrivateUsage]
    needs = await line.skill_needs("ag_ops_team_a")
    assert needs == {"sk_clients": "needs Salesforce, on · you are not signed in (a call shows a Connect card)"}


async def test_each_skills_index_line_carries_its_apps_state() -> None:
    class Apps:
        async def fragment(self, agent_id: str) -> PromptFragment | None:
            return PromptFragment("Apps for this conversation: Salesforce: on", False)

        async def skill_needs(self, agent_id: str) -> dict[str, str]:
            return {"sk_clients": "needs Salesforce, on · you are signed in"}

    clients = Skill(
        "sk_clients", 1, "Salesforce clients", "salesforce-clients", "A client in Salesforce", "on_match", "x"
    )
    settings = AgentSettings("ag", 1, [], "m", skills=[clients])
    out = await with_apps(SimpleNamespace(apps=Apps()), settings, "ag")  # type: ignore[arg-type]
    assert out.skills[0].use_when == "A client in Salesforce (needs Salesforce, on · you are signed in)"
    assert out.instructions[-1].text.startswith("Apps for this conversation")


def test_an_app_this_chat_left_out_reads_as_left_out_not_as_on() -> None:
    # The person left Salesforce out of this chat from the composer: read as on, the model went looking for its tools.
    from ops_agents.api.apps_line import left_out  # noqa: PLC0415

    cards = [card("Salesforce", "connected"), card("GitHub", "connected")]
    cards[0]["moduleIds"], cards[1]["moduleIds"] = ["mod_sf"], ["mod_gh"]
    module_of = {"salesforce_query": "mod_sf", "salesforce_get_record": "mod_sf", "github_list_issues": "mod_gh"}
    held = list(module_of)
    marked = left_out(cards, held, module_of, {"salesforce_query", "salesforce_get_record"})
    text = render(marked) or ""
    assert "Salesforce: left out of this chat" in text and "GitHub: on" in text, text
    # One of an app's tools switched off in the settings panel leaves the app in the chat.
    assert "left out" not in (render(left_out(cards, held, module_of, {"salesforce_query"})) or "")
