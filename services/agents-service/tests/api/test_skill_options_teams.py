"""A skill's owner team, by failure mode: New skill's Owner team offers a team id with no name, or only teams that
already own a skill, so a first skill cannot be made; a create stores any text the caller sends as the owner team; the
list, its filter and the skill page show the stored id where a person reads a team name."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_widget_embed import BUILDER, OUTSIDER, VIEWER
from tests.api.test_widget_route_pins import client  # pyright: ignore[reportPrivateUsage]

__all__ = ["client"]

SKILL = {"name": "Statement copy", "useWhen": "A customer asks for a past statement.", "instructions": "Send it."}


async def test_options_offer_the_builders_team_by_id_and_name_before_any_skill_exists(client: AsyncClient) -> None:
    built = (await client.get("/v1/skills/options", headers=BUILDER)).json()["data"]
    other = (await client.get("/v1/skills/options", headers=OUTSIDER)).json()["data"]
    assert built["ownerTeams"] == [{"id": "team_ops", "name": "Operations"}], built
    assert other["ownerTeams"] == [{"id": "team_fraud", "name": "Fraud Operations"}], other
    assert built["teams"] == ["team_ops"]


async def test_options_offer_no_team_to_a_caller_who_may_not_create(client: AsyncClient) -> None:
    viewer = await client.get("/v1/skills/options", headers=VIEWER)
    assert viewer.status_code == 200, viewer.text
    assert viewer.json()["data"]["ownerTeams"] == []


async def test_a_create_refuses_an_owner_team_the_caller_may_not_create_in(client: AsyncClient) -> None:
    for owner in ("Customer Support", "team_fraud"):
        refused = await client.post("/v1/skills", json={**SKILL, "ownerTeam": owner}, headers=BUILDER)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["code"] == "unknown_owner_team", refused.text


async def test_the_list_its_filter_and_the_skill_page_name_the_owner_team(client: AsyncClient) -> None:
    made = await client.post("/v1/skills", json=SKILL, headers=BUILDER)
    assert made.status_code == 201, made.text
    skill = made.json()["data"]
    assert skill["ownerTeam"] == "team_ops", skill
    listed = (await client.get("/v1/skills", params={"search": "Statement copy"}, headers=BUILDER)).json()["data"]
    assert [(r["ownerTeam"], r["ownerTeamName"]) for r in listed["data"]] == [("team_ops", "Operations")], listed
    assert listed["teamNames"] == {"team_ops": "Operations"}, listed
    page = (await client.get(f"/v1/skills/{skill['id']}", headers=BUILDER)).json()["data"]
    assert page["ownerTeamName"] == "Operations", page
