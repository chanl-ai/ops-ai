"""The agents service with the model gateway in-process: models-service on the same test database, its provider
answered by a scripted model, so a turn's budget and replay are the gateway's own (docs/design/agents-v2/
model-gateway.md). For the tests that are about a budget or a re-run; every other test talks to the scripted model
directly (tests/conftest.py)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

import httpx
import httpx2
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agent_kernel.testing import Script, ScriptedModel
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_models.app import create_models_app
from ops_service_kit.settings import Settings
from tests.api.test_write_approval_policy import _Names, introspect, jwks  # pyright: ignore[reportPrivateUsage]
from tests.conftest import SEED, FakeGraphModels, empty_engine, fixture_knowledge, response_checker, scripted

ALIAS = "bank-standard"


def _service() -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="models", tenant_id="local", scopes=["models:budgets"]
    )
    return {"Authorization": f"Bearer {token}"}


def provider(script: ScriptedModel) -> httpx.AsyncClient:
    """The gateway's upstream: each provider request answered by `script`, as an OpenAI-compatible provider would."""

    async def handle(request: httpx.Request) -> httpx.Response:
        sent = httpx2.Request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
        got = await script.handle_async_request(sent)
        body = await got.aread()
        return httpx.Response(got.status_code, headers=dict(got.headers), content=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@dataclass
class Gateway:
    app: FastAPI
    client: AsyncClient
    models: AsyncClient
    provider: ScriptedModel

    @property
    def runtime(self) -> Runtime:
        return cast(Runtime, self.app.state.runtime)

    async def budget(self, budget_id: str) -> dict[str, Any]:
        r = await self.models.get(f"/v1/models/budgets/{budget_id}", headers=_service())
        assert r.status_code == 200, r.text
        return cast(dict[str, Any], r.json()["data"])


@dataclass
class Models:
    """models-service in-process: its app, a client of it, the completions client the kernel's model sends through,
    the agents key's secret, and the scripted provider behind it."""

    app: FastAPI
    client: AsyncClient
    completions: httpx2.AsyncClient
    secret: str
    provider: ScriptedModel


@asynccontextmanager
async def models_gateway(engine: AsyncEngine, script: Script = scripted) -> AsyncGenerator[Models]:
    """models-service on `engine` with `ALIAS` priced at one dollar per thousand tokens on a scripted provider, and a
    key of kind `purpose` as the dev seed gives the agents service."""
    answered = ScriptedModel(script)
    models_app = create_models_app(
        engine, provider_secrets={"UPSTREAM_KEY": "sk-upstream"}, upstream=provider(answered)
    )
    async with (
        models_app.router.lifespan_context(models_app),
        AsyncClient(transport=ASGITransport(app=models_app), base_url="http://models") as models,
    ):
        conn = {"name": f"up-{uuid4().hex[:8]}", "type": "openai-compatible", "baseUrl": "http://up/v1"}
        made = await models.post("/v1/models/providers", json={**conn, "keyRef": "UPSTREAM_KEY"}, headers=_service())
        assert made.status_code == 201, made.text
        version = {"providerId": made.json()["data"]["id"], "modelId": "gpt-up", "clearedSensitivity": "internal"}
        priced = {**version, "inputPerMillion": "1000", "outputPerMillion": "1000"}
        # The alias outlives a test (only the agents tables are emptied): a later test adds a version on its provider.
        r = await models.post("/v1/models/aliases", json={"name": ALIAS, **priced}, headers=_service())
        if r.status_code == 409:
            r = await models.post(f"/v1/models/aliases/{ALIAS}/versions", json=priced, headers=_service())
        assert r.status_code in (200, 201), r.text
        key = {"id": f"agents:test_{uuid4().hex[:8]}", "kind": "purpose", "budget": "50"}
        r = await models.post("/v1/models/keys", json=key, headers=_service())
        assert r.status_code == 201, r.text
        completions = httpx2.AsyncClient(transport=httpx2.ASGITransport(app=models_app))
        yield Models(models_app, models, completions, str(r.json()["data"]["secret"]), answered)


@asynccontextmanager
async def through_gateway(
    engine: AsyncEngine, graph_models: Any, script: Script = scripted, *, checked: bool = False, **wiring: Any
) -> AsyncGenerator[Gateway]:
    """The agents app whose model calls go through models-service (`models_gateway`). `checked` holds every reply to
    its documented schema, as `tests.conftest.started` does."""
    async with models_gateway(engine, script) as m:
        settings = Settings(
            database_url=str(engine.url.render_as_string(hide_password=False)),
            seed_dir=SEED,
            models_url="http://models",
            models_key=SecretStr(m.secret),
            model_alias=ALIAS,
        )
        app = create_app(
            settings,
            engine=engine,
            checkpointer=wiring.pop("checkpointer", None) or InMemorySaver(),
            graph_models=graph_models,
            knowledge=fixture_knowledge(),
            models_client=AsyncClient(transport=ASGITransport(app=m.app), base_url="http://models"),
            completions_client=m.completions,
            **wiring,
        )
        hooks = {"response": [response_checker(app)]} if checked else {}
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://test", event_hooks=hooks) as client,
        ):
            yield Gateway(app, client, m.client, m.provider)


@asynccontextmanager
async def platform_through_gateway(database_url: str) -> AsyncGenerator[AsyncClient]:
    """`test_write_approval_policy.dev_platform` (platform-signed people, the scripted model, team names) with its
    model calls through the gateway on the PostgreSQL test database, for the tests about a conversation's budget."""
    settings = Settings(database_url=database_url, seed_dir=SEED)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
    )
    async with empty_engine(database_url) as engine, through_gateway(engine, FakeGraphModels(), auth=auth) as g:
        g.runtime.team_names = _Names()
        yield g.client
