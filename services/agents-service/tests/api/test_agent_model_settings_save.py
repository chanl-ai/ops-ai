"""A save's model settings are checked against the knobs of the agent's alias, as models-service answers them: a knob
the model does not take, or a value outside its range, is refused naming the knob; one that fits is saved and read
back. models-service is faked at the alias port, with the knobs reply of a Claude model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.http import Json
from ops_service_kit.settings import Settings

from ..conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from ..contract import response_checker

CLAUDE: Json = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "temperature": {"type": "number", "title": "Temperature", "minimum": 0, "maximum": 1, "default": 1},
        "thinking_budget": {"type": "integer", "title": "Thinking budget (tokens)", "minimum": 0, "x-minimum-on": 1024},
    },
}


class Knobs:
    async def chat_models(self) -> list[Json]:
        return [{"name": "bank-standard", "kind": "chat"}]

    async def knobs(self, alias: str) -> Json:
        return {"alias": alias, "version": 1, "modelId": "claude-sonnet-4-6", "catalogued": True, "knobs": CLAUDE}


async def test_a_save_is_held_to_the_alias_knobs(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"
    engine = create_async_engine(url)
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        Settings(database_url=url, seed_dir=SEED),
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        knowledge=fixture_knowledge(),
    )
    hooks = {"response": [response_checker(app)]}
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", event_hooks=hooks) as c,
    ):
        app.state.runtime.model_aliases = Knobs()
        made = await c.post("/v1/agents", json={"name": "Claims Helper", "role": "answers claims", "model": "fast"})
        assert made.status_code == 201, made.text

        async def save(settings: dict[str, Any]) -> Any:
            held = (await c.get(f"/v1/agents/{made.json()['data']['id']}")).json()["data"]
            base = {"baseVersion": held["version"], "baseDigest": held["digest"]}
            return await c.patch(f"/v1/agents/{held['id']}", json={"modelSettings": settings, **base})

        too_hot, unsupported, too_small = (
            await save({"temperature": 1.5}),
            await save({"top_k": 40}),
            await save({"thinking_budget": 100}),
        )
        refused = [
            (r.status_code, r.json()["error"]["code"], r.json()["error"]["message"])
            for r in (too_hot, unsupported, too_small)
        ]
        assert [(s, code) for s, code, _ in refused] == [(422, "model_setting_invalid")] * 3, refused
        assert "Temperature" in refused[0][2] and "top_k" in refused[1][2] and "1024" in refused[2][2], refused

        kept = await save({"temperature": 0.2, "thinking_budget": 0})
        assert kept.status_code == 200, kept.text
        assert kept.json()["data"]["modelSettings"] == {"temperature": 0.2, "thinking_budget": 0}, kept.json()["data"]
