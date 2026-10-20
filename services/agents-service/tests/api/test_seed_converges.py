"""A seeded agent follows its seed file (c-067), by failure mode: a changed seed never reaching a database seeded
before it (the shared stack keeps knowledge bases the seed no longer names), and the seed overwriting an agent a
person has since published."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI
from httpx import ASGITransport

from ops_agents.api.deps import Runtime

from ..conftest import SEED
from .test_agent_registry import _app  # pyright: ignore[reportPrivateUsage]


def agents_file(tmp_path: Path, **collections: list[str]) -> Path:
    agents: list[dict[str, Any]] = json.loads((SEED / "chat_agents.json").read_text())
    for a in agents:
        if a["id"] in collections:
            a["default_kb_ids"] = collections[a["id"]]
    path = tmp_path / "chat_agents.json"
    path.write_text(json.dumps(agents))
    return path


async def test_a_changed_seed_reaches_agents_seeded_before_it(tmp_path: Path) -> None:
    db = str(tmp_path / "db.sqlite")
    async with _app(db, agents_seed_file=agents_file(tmp_path)) as c:
        before = (await c.get("/v1/agents/ag_fraud")).json()["data"]
        assert before["collections"] == ["kb_people", "kb_eng"]
        # A person publishes their own version of the branch agent; the seed must leave it alone from now on.
        r = await c.patch("/v1/agents/ag_branch", json={"instructions": "Answer in French.", "note": "mine"})
        await c.post("/v1/agents/ag_branch/publish-requests", json={"version": r.json()["data"]["version"]})
    async with _app(db, agents_seed_file=agents_file(tmp_path, ag_fraud=[], ag_branch=[])) as c:
        fraud = (await c.get("/v1/agents/ag_fraud")).json()["data"]
        assert fraud["collections"] == [] and fraud["publishedVersion"] == fraud["version"] > before["version"], fraud
        changes = (await c.get("/v1/agents/ag_fraud/versions")).json()["data"][0]["changes"]
        assert "Changed knowledge bases" in changes, changes
        branch = (await c.get("/v1/agents/ag_branch")).json()["data"]
        assert branch["collections"] == ["kb_support"] and branch["instructions"] == "Answer in French.", branch
    async with _app(db, agents_seed_file=agents_file(tmp_path, ag_fraud=[], ag_branch=[])) as c:
        again = (await c.get("/v1/agents/ag_fraud")).json()["data"]
        assert again["version"] == fraud["version"], "an unchanged seed makes no new version"


async def test_the_seeded_advisor_serves_its_guardrail_with_every_topic_scoped(tmp_path: Path) -> None:
    """The scope is what lets the advisor compare the bank's savings products while refusing advice on securities; a
    pin without it refuses both (seen live on gpt-5-nano)."""
    # guardrails.json and skills.json are read beside the agents file: the dev seed's.
    async with _app(str(tmp_path / "db.sqlite"), agents_seed_file=SEED.parents[2] / "seed" / "chat_agents.json") as c:
        transport = cast(ASGITransport, c._transport)  # pyright: ignore[reportPrivateUsage]
        rt = cast(Runtime, cast(FastAPI, transport.app).state.runtime)
        advisor = rt.catalog.agent("ag_advisor")
        assert advisor is not None and advisor.guardrails, "the dev seed pins a guardrail on the advisor"
        for g in advisor.guardrails:
            assert set(g.scopes) == set(g.topics), (g.name, g.version, g.scopes)
