"""A brief draft proposes a text per heading from the scripted model and saves nothing: the agent's version and copy
are the same after it, so a draft the builder skips leaves no trace."""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import DRAFTED_BRIEF


async def test_a_draft_returns_each_heading_and_writes_nothing(client: AsyncClient) -> None:
    before = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    r = await client.post("/v1/agents/ag_fraud/brief-draft", json={"description": "Answers loan status questions."})
    assert r.status_code == 200, r.text
    assert r.json()["data"] == DRAFTED_BRIEF
    after = (await client.get("/v1/agents/ag_fraud")).json()["data"]
    assert (after["version"], after["digest"], after["brief"]) == (before["version"], before["digest"], before["brief"])
