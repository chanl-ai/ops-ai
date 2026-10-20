"""Agent limits callers override within (c-068 T005 to T008), by failure mode: a version saved before limits has no
limits or ones wider than the owner's defaults; a draft's limits reach what is live before a publish, or a publish
does not carry them to the served definition and the reviewer; a limit that disagrees with itself or its version is
saved, or silently clamped instead of refused with 422 naming the field; a model change leaves a stale allowed model;
an allowed model models-service does not serve is published."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.graphs import metadata
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings
from tests.conftest import fixture_knowledge

from ..conftest import SEED, FakeGraphModels, scripted_model
from ..contract import response_checker
from .test_agent_registry import _models_service  # pyright: ignore[reportPrivateUsage]

FRAUD = "ag_fraud"
LIMITS: dict[str, Any] = {
    "allowedModels": ["bank-standard", "bank-mini"],
    "defaultModel": "bank-standard",
    "temperature": {"min": 0, "max": 0.7, "default": 0.2},
    "budget": {"ceilingUsd": 2, "defaultUsd": 0.5},
    "allowedKnowledgeBaseIds": ["kb_people", "kb_eng", "kb_support"],
    "switchableToolIds": ["place_wire_hold"],
    "callersMayAddInstructions": True,
    "publicKeyMay": ["tools", "knowledge"],
}


@asynccontextmanager
async def _app(tmp_path: Path, **settings: Any) -> AsyncGenerator[tuple[AsyncClient, FastAPI]]:
    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        Settings(database_url=url, seed_dir=SEED, **settings),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
        models_client=_models_service() if "models_url" in settings else None,
    )
    async with (
        app.router.lifespan_context(app),
        AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t", event_hooks={"response": [response_checker(app)]}
        ) as c,
    ):
        yield c, app


def _data(r: Any, status: int = 200) -> Any:
    assert r.status_code == status, r.text
    return r.json()["data"]


def served(app: FastAPI, agent_id: str) -> dict[str, Any]:
    rt: Runtime = app.state.runtime
    agent = rt.catalog.agent(agent_id)
    assert agent is not None and agent.limits is not None
    return agent.limits.wire()


async def test_a_version_saved_before_limits_gets_the_owners_defaults(tmp_path: Path) -> None:
    async with _app(tmp_path) as (c, app):
        fraud = _data(await c.get(f"/v1/agents/{FRAUD}"))
        assert fraud["limits"] == {
            "allowedModels": [fraud["model"]],
            "defaultModel": fraud["model"],
            "allowedKnowledgeBaseIds": fraud["collections"],
            "switchableToolIds": fraud["toolIds"],
            "callersMayAddInstructions": False,
            # Every pinned widget may be switched off by default (c-071 narrowing, agreed with c-082); FRAUD pins none.
            "switchableWidgetIds": [],
            "publicKeyMay": ["tools", "knowledge", "budget", "outputSchema", "variables"],
        }
        assert served(app, FRAUD) == fraud["limits"]


async def test_limits_go_live_only_through_a_reviewed_publish(tmp_path: Path) -> None:
    async with _app(tmp_path, models_url="http://models") as (c, app):
        before = served(app, FRAUD)
        await c.patch(
            f"/v1/agents/{FRAUD}",
            json={"model": "bank-standard", "limits": {**LIMITS, "allowedModels": ["bank-standard"]}},
        )
        draft = _data(await c.get(f"/v1/agents/{FRAUD}"))
        assert draft["limits"]["temperature"] == {"min": 0, "max": 0.7, "default": 0.2}
        assert served(app, FRAUD) == before, "a draft's limits are not what callers get"
        versions = _data(await c.get(f"/v1/agents/{FRAUD}/versions"))
        assert "Changed caller limits" in versions[0]["changes"]

        review = _data(await c.post(f"/v1/agents/{FRAUD}/publish-requests", json={"version": draft["version"]}), 201)
        assert review["agentPublish"]["limits"] == draft["limits"], "the reviewer sees the limits being approved"
        assert served(app, FRAUD) == draft["limits"]


async def test_a_limit_that_disagrees_with_itself_or_its_version_is_refused_naming_it(tmp_path: Path) -> None:
    model = "default"
    good = {**LIMITS, "allowedModels": [model, "bank-mini"], "defaultModel": model}
    cases: list[tuple[dict[str, Any], str]] = [
        ({"temperature": {"min": 0, "max": 0.7, "default": 0.9}}, "limits.temperature.default"),
        ({"temperature": {"min": 0.8, "max": 0.2, "default": 0.5}}, "limits.temperature"),
        ({"budget": {"ceilingUsd": 2, "defaultUsd": 3}}, "limits.budget.defaultUsd"),
        ({"defaultModel": "bank-mini"}, "limits.defaultModel"),
        ({"allowedModels": ["bank-mini"]}, "limits.defaultModel"),
        ({"allowedKnowledgeBaseIds": ["kb_people"]}, "limits.allowedKnowledgeBaseIds"),
        ({"switchableToolIds": ["issue_provisional_credit"]}, "limits.switchableToolIds"),
    ]
    async with _app(tmp_path) as (c, _):
        fraud = _data(await c.get(f"/v1/agents/{FRAUD}"))
        assert fraud["model"] == model
        for change, field in cases:
            r = await c.patch(f"/v1/agents/{FRAUD}", json={"limits": {**good, **change}})
            assert r.status_code == 422, (change, r.text)
            assert r.json()["error"]["code"] == "invalid_limits" and r.json()["error"]["message"].startswith(field), (
                change,
                r.text,
            )
        assert _data(await c.get(f"/v1/agents/{FRAUD}"))["version"] == fraud["version"], "nothing was saved"

        _data(await c.patch(f"/v1/agents/{FRAUD}", json={"limits": good}))
        moved = await c.patch(f"/v1/agents/{FRAUD}", json={"model": "bank-mini"})
        assert moved.status_code == 422 and moved.json()["error"]["message"].startswith("limits.defaultModel"), (
            moved.text
        )
        dropped = await c.patch(f"/v1/agents/{FRAUD}", json={"toolIds": ["lookup_account"]})
        assert dropped.status_code == 422 and "switchableToolIds" in dropped.json()["error"]["message"], dropped.text


async def test_an_allowed_model_models_service_does_not_serve_is_not_published(tmp_path: Path) -> None:
    async with _app(tmp_path, models_url="http://models") as (c, _):
        limits = {**LIMITS, "allowedModels": ["bank-standard", "bank-embed"]}
        agent = _data(await c.patch(f"/v1/agents/{FRAUD}", json={"model": "bank-standard", "limits": limits}))
        r = await c.post(f"/v1/agents/{FRAUD}/publish-requests", json={"version": agent["version"]})
        assert r.status_code == 422 and r.json()["error"]["code"] == "unknown_model_alias", r.text
        assert "bank-embed" in r.json()["error"]["message"]
