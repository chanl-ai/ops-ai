"""An app the team has off, or two accounts that fit, in chat, by failure mode: the assistant has no way to draw a
card for it, so it answers in a sentence with nothing to press; the card names an app that is on, or one the install
does not have; and the model reads the gateway's code, or a line telling it to send the person elsewhere, instead of one
sentence about the card."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from ops_agents.activities.gateway import carded
from ops_agents.api.auth import Principal
from ops_agents.api.child_runs import TURN_PERSON
from ops_agents.api.error_words import worded
from ops_agents.api.ops_tools import REQUEST_APP, OpsReads

SAM = Principal(name="Sam Adeyemi", email="s.adeyemi@harborpine.example", team_id="team_security", tenant_id="local")


class Line:
    """The apps line's cards for the turn's team and person."""

    async def cards(self, team: str, email: str, now: float | None = None) -> list[dict[str, Any]]:
        assert (team, email) == (SAM.team_id, SAM.email)
        return [
            {"id": "plugin:opsai.salesforce", "name": "Salesforce", "appState": "not_installed"},
            {"id": "plugin:opsai.github", "name": "GitHub", "appState": "connected"},
        ]


async def _run(app: str) -> Any:
    reads = OpsReads(SimpleNamespace(apps_line=Line(), app_states=object()))  # type: ignore[arg-type]
    token = TURN_PERSON.set(SAM)
    try:
        return await reads.run(REQUEST_APP, {"app": app})
    finally:
        TURN_PERSON.reset(token)


async def test_an_app_the_team_has_off_comes_back_as_the_gateways_refusal_with_its_app_and_team() -> None:
    out = await _run("salesforce")
    assert out.ok is False
    error = out.output["error"]
    assert error["code"] == "APP_OFF_FOR_TEAM", error
    assert error["details"] == {"app": "Salesforce", "appId": "plugin:opsai.salesforce", "teamId": "team_security"}
    said = str(out.for_model)
    assert "card above" in said and "APP_OFF_FOR_TEAM" not in said and "Connectors" not in said, said


async def test_an_app_that_is_on_or_unknown_draws_no_card() -> None:
    for app in ("GitHub", "Core banking"):
        out = await _run(app)
        assert out.ok is False and "code" not in out.output["error"], out.output


def test_the_gateways_own_refusal_reads_as_the_same_card_line_and_words() -> None:
    refused = {"error": {"code": "APP_OFF_FOR_TEAM", "message": "x", "details": {"app": "Salesforce"}}}
    assert "Salesforce is installed but off for this team" in str(carded(refused))
    words = worded("salesforce_query", refused)
    assert words is not None and words["what"] == "Salesforce is off for this team" and words["retryable"] is False


def test_two_accounts_and_no_default_read_as_one_sentence_about_the_card() -> None:
    refused = {
        "error": {
            "code": "ACCOUNT_CHOICE_NEEDED",
            "message": "x",
            "details": {"app": "GitHub", "accounts": [{"connectionId": "a"}, {"connectionId": "b"}]},
        }
    }
    said = str(carded(refused))
    assert "2 GitHub accounts" in said and "card above" in said and "ACCOUNT_CHOICE_NEEDED" not in said, said
    words = worded("github_list_issues", refused)
    assert words is not None and words["what"] == "Two of your GitHub accounts fit", words
