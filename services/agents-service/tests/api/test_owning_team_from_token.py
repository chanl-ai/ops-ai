"""An agent's and a workflow's owning team come from the caller's token (c-171): a body naming an owner is refused,
so nobody labels a record as another team's, and the record answers with the team id the console names from its own
teams list, which stays right when a team is renamed."""

from __future__ import annotations

from httpx import AsyncClient

CARDS = {"X-Team-Id": "team_cards"}


async def test_an_agent_is_owned_by_the_callers_team_and_a_body_cannot_name_another(client: AsyncClient) -> None:
    body = {"name": "Labelled", "role": "r", "owner": "Operations"}
    named = await client.post("/v1/agents", json=body, headers=CARDS)
    assert named.status_code == 400, named.text
    made = (await client.post("/v1/agents", json={"name": "Carded", "role": "r"}, headers=CARDS)).json()["data"]
    assert made["teamId"] == "team_cards" and "owner" not in made, made
    moved = await client.patch(f"/v1/agents/{made['id']}", json={"owner": "Operations"}, headers=CARDS)
    assert moved.status_code == 400, moved.text


async def test_a_workflow_is_owned_by_the_callers_team_and_a_body_cannot_name_another(client: AsyncClient) -> None:
    named = await client.post("/v1/workflows", json={"name": "Labelled", "owner": "Operations"}, headers=CARDS)
    assert named.status_code == 400, named.text
    made = (await client.post("/v1/workflows", json={"name": "Carded flow"}, headers=CARDS)).json()["data"]
    assert made["teamId"] == "team_cards" and "owner" not in made, made
    moved = await client.patch(f"/v1/workflows/{made['id']}", json={"owner": "Operations"}, headers=CARDS)
    assert moved.status_code == 400, moved.text
