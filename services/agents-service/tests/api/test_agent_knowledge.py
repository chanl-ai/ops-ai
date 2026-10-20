"""An agent's knowledge holds knowledge base ids only (c-141), by failure mode: a name saved where the runtime reads
ids; an agent made unsaveable because a base it already held is gone; a save accepted unchecked while kb-service
cannot answer."""

from __future__ import annotations

from pathlib import Path

import pytest

from ops_agents.activities.knowledge import NoKnowledgeService
from ops_agents.api.agent_registry import registry
from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope

from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]

AGENT = "ag_branch"


async def test_a_name_is_refused_and_an_id_saves(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, _):
        named = await c.patch(f"/v1/agents/{AGENT}", json={"collections": ["Retail banking"]})
        assert named.status_code == 422, named.text
        assert named.json()["error"]["code"] == "unknown_knowledge_base" and "Retail banking" in named.text
        saved = _data(await c.patch(f"/v1/agents/{AGENT}", json={"collections": ["kb_people"]}))
        assert saved["collections"] == ["kb_people"]


async def test_a_value_already_held_is_kept(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        reg = registry(app.state.runtime)
        # As the start-up seed saves: in the dev tenant, which a request sets from its token.
        with tenant_scope(LOCAL_TENANT):
            row = await reg.row(AGENT)
            spec = dict((await reg.version(AGENT, int(row["version"])))["spec"])
            await reg.save(AGENT, {**spec, "collections": ["kb_gone"]}, by="seed")
        kept = await c.patch(f"/v1/agents/{AGENT}", json={"collections": ["kb_gone", "kb_people"]})
        assert kept.status_code == 200, kept.text


async def test_adding_knowledge_while_kb_service_is_down_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _app(tmp_path) as (c, app):
        monkeypatch.setattr(app.state.runtime, "kbs", NoKnowledgeService)
        down = await c.patch(f"/v1/agents/{AGENT}", json={"collections": ["kb_people"]})
        assert down.status_code == 503, down.text
