"""Every GET route of models-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its rows, a route over its row, a route that opens a second
transaction or checks out a second connection, and a provider asked while the request holds a transaction (the
provider key's model list), which the budget's service-call count cannot see, since the provider is not a service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ops_identity.fastapi import current_principal
from ops_models.app import create_models_app
from ops_service_kit.contract import response_checker
from ops_service_kit.public_address import PublicFetch
from ops_service_kit.request_timing import current
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check

from .conftest import ADMIN, SERVICE, Models
from .test_provider_key_check import Resolver
from .test_provider_keys import people

BUDGETS = Path(__file__).parents[1] / "budgets.toml"
KEY = "sk-budget"

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
def held() -> list[int]:
    """The transactions the request held open at each provider call."""
    return []


def _provider(held: list[int]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        timing = current()
        held.append(timing.db_tx_open if timing is not None else -1)
        return httpx.Response(200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:8]}"


@pytest.fixture
def app(models: Models, held: list[int], tenant: str) -> FastAPI:
    fetch = PublicFetch(resolver=Resolver(), max_redirects=0)
    built = create_models_app(models.engine, upstream=_provider(held), key_fetch=fetch)
    # A request with no bearer token is an account admin of `tenant`: the provider key routes are a person's.
    built.dependency_overrides[current_principal] = people(tenant)
    return built


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    hooks = {"response": [response_checker(app)]}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://models", event_hooks=hooks) as http:
        yield http


@pytest.fixture
def seed_team(app: FastAPI, client: httpx.AsyncClient, models: Models) -> SeedTeam:
    """`n` more of each list: connections, aliases and one alias's versions, model keys, calls on one key, and the
    account's provider keys. The versioned alias and a provider key share one name, since both paths name `{name}`.
    A request with no bearer token is an account admin (`app`), who reads the provider keys and connections; the
    routes budgets.toml marks `caller = "service"` are called with the service token."""
    http = client
    name = f"budget-{uuid4().hex[:8]}"
    on_app = Models(http, models.engine, app)

    async def seed(n: int) -> Seeded:
        version = {"providerId": "prov_scripted", "modelId": "scripted-standard", "clearedSensitivity": "internal"}
        if (await http.get(f"/v1/models/aliases/{name}/versions", headers=SERVICE)).status_code == 404:
            made = await http.post("/v1/models/aliases", json={"name": name, **version}, headers=ADMIN)
            assert made.status_code == 201, made.text
        assert (await http.put(f"/v1/provider-keys/{name}", json={"value": KEY})).status_code == 200
        _, secret = await on_app.key(budget="100")
        for i in range(n):
            tag = f"{name}-{n}-{i}"
            conn = {"name": tag, "type": "openai-compatible", "baseUrl": "http://up/v1"}
            assert (await http.post("/v1/models/providers", json=conn, headers=ADMIN)).status_code == 201
            alias = {"name": tag, **version}
            assert (await http.post("/v1/models/aliases", json=alias, headers=ADMIN)).status_code == 201
            added = await http.post(f"/v1/models/aliases/{name}/versions", json=version, headers=ADMIN)
            assert added.status_code == 201, added.text
            await on_app.key()
            assert (await on_app.complete(secret)).status_code == 200
            assert (await http.put(f"/v1/provider-keys/{tag}", json={"value": KEY})).status_code == 200
        return Seeded(headers={}, ids={"name": name, "provider_id": "prov_scripted"}, service_headers=SERVICE)

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget, held: list[int]) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
    assert held, "the provider key's model list asked the provider"
    assert set(held) == {0}, f"the provider was asked with a transaction open: {held}"
