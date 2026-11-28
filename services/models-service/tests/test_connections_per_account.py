"""Model connections are an account's own, by failure mode: another account lists them; reads or re-points one by id;
calls a model through an alias bound to one, which would send its prompt to that account's endpoint; binds an alias of
its own to one; SQL that names no tenant reads or changes them, which only the database policy stops; and a new
account has no `default` alias of its own, so its chat falls back to another account's. Each refusal is the 404 an
unknown id gets, so an id never tells an account that another account holds it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from ops_access.platform_events import TEAM_CREATED
from ops_identity import dev_service_signer, mint_service_token
from ops_identity.fastapi import current_principal, current_tenant_caller
from ops_models.app import create_models_app
from ops_models.seed import OPENAI_LOCAL, connection_id, seed_account
from ops_models.store.tables import provider_connections
from ops_service_kit.contract import response_checker
from ops_store import isolation
from ops_store.schema import isolation_kind

from .conftest import Models, service_as
from .test_provider_keys import people

ROLE = "ops_models_tenant"


@dataclass
class Account:
    tenant: str
    client: httpx.AsyncClient


@dataclass
class Rig:
    a: Account
    b: Account
    models: Models
    seen: list[str]
    secret: str
    connection: str
    alias: str

    async def complete(self, tenant: str) -> httpx.Response:
        return await self.models.complete(self.secret, alias=self.alias, **{"X-Tenant-Id": tenant})


def _upstream(seen: list[str]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        choice = {"index": 0, "message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
        usage = {"prompt_tokens": 5, "completion_tokens": 2}
        return httpx.Response(200, json={"id": "up", "object": "chat.completion", "choices": [choice], "usage": usage})

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


@pytest.fixture
async def rig(models: Models) -> AsyncIterator[Rig]:
    seen: list[str] = []
    upstream = _upstream(seen)
    accounts: list[Account] = []
    for _ in range(2):
        tenant = f"t_{uuid4().hex[:8]}"
        app = create_models_app(models.engine, upstream=upstream)
        # Each account's admin, who is not its Owner: settings.manage writes connections and aliases alike.
        # The connection and alias routes take the tenant caller, the key routes the principal: both are this person.
        app.dependency_overrides[current_principal] = people(tenant)
        app.dependency_overrides[current_tenant_caller] = people(tenant)
        hooks = {"response": [response_checker(app)]}
        transport = httpx.ASGITransport(app=app)
        accounts.append(Account(tenant, httpx.AsyncClient(transport=transport, base_url="http://m", event_hooks=hooks)))
    a, b = accounts
    tag = uuid4().hex[:8]
    made = await a.client.post(
        "/v1/models/providers",
        json={"name": f"harbor-{tag}", "type": "openai-compatible", "baseUrl": "https://llm.harborpine.example/v1"},
    )
    assert made.status_code == 201, made.text
    connection = made.json()["data"]["id"]
    alias = f"harbor-chat-{tag}"
    bound = {"name": alias, "providerId": connection, "modelId": "harbor-chat", "clearedSensitivity": "internal"}
    assert (await a.client.post("/v1/models/aliases", json=bound)).status_code == 201
    on_app = Models(a.client, models.engine)
    _, secret = await on_app.key(budget="5")
    try:
        yield Rig(a, b, on_app, seen, secret, connection, alias)
    finally:
        for account in accounts:
            await account.client.aclose()


async def test_another_account_lists_none_of_the_connections_and_may_reuse_a_name(rig: Rig) -> None:
    mine = (await rig.a.client.get("/v1/models/providers", params={"ids": rig.connection})).json()["data"]["data"]
    assert [c["id"] for c in mine] == [rig.connection]
    theirs = (await rig.b.client.get("/v1/models/providers")).json()["data"]["data"]
    assert rig.connection not in [c["id"] for c in theirs], "another account listed the connection"
    name = mine[0]["name"]
    same = await rig.b.client.post(
        "/v1/models/providers", json={"name": name, "type": "openai-compatible", "baseUrl": "https://b.example/v1"}
    )
    assert same.status_code == 201, f"a name held by another account answered {same.status_code}: {same.text}"


async def test_another_account_reads_or_repoints_the_connection_by_id_as_not_found(rig: Rig) -> None:
    b = rig.b.client
    catalog = await b.get(f"/v1/models/providers/{rig.connection}/catalog")
    moved = await b.put(f"/v1/models/providers/{rig.connection}", json={"baseUrl": "https://collect.example/v1"})
    assert (catalog.status_code, moved.status_code) == (404, 404), (catalog.text, moved.text)
    held = (await rig.a.client.get("/v1/models/providers", params={"ids": rig.connection})).json()["data"]["data"]
    assert held[0]["baseUrl"] == "https://llm.harborpine.example/v1", "another account re-pointed the connection"


async def test_another_account_calls_no_model_through_an_alias_bound_to_the_connection(rig: Rig) -> None:
    refused = await rig.complete(rig.b.tenant)
    assert refused.status_code == 404, refused.text
    assert rig.seen == [], "another account's prompt reached the connection's endpoint"
    knobs = await rig.b.client.get(f"/v1/models/aliases/{rig.alias}/knobs")
    listed = (await rig.b.client.get("/v1/models/aliases", params={"ids": rig.alias})).json()["data"]["data"]
    assert (knobs.status_code, listed) == (404, []), knobs.text
    # Nor through an alias of its own bound to the connection.
    fields = {"providerId": rig.connection, "modelId": "harbor-chat", "clearedSensitivity": "internal"}
    created = await rig.b.client.post("/v1/models/aliases", json={"name": f"borrow-{uuid4().hex[:8]}", **fields})
    versioned = await rig.b.client.post(f"/v1/models/aliases/{rig.alias}/versions", json=fields)
    assert (created.status_code, versioned.status_code) == (404, 404), (created.text, versioned.text)
    served = await rig.complete(rig.a.tenant)
    assert served.status_code == 200 and rig.seen == ["llm.harborpine.example"], served.text


async def test_sql_naming_no_tenant_reads_or_changes_no_other_accounts_connection(rig: Rig, database_url: str) -> None:
    assert isolation_kind(provider_connections) == "tenant"
    engine = create_async_engine(database_url)
    try:
        with isolation.scope(rig.b.tenant, None):
            async with isolation.isolated_tx(engine, role=ROLE) as c:
                pid = {"pid": rig.connection}
                seen = await c.execute(sa.text("SELECT count(*) FROM provider_connections WHERE id = :pid"), pid)
                assert seen.scalar_one() == 0, "another account read the connection"
                moved = await c.execute(
                    sa.text("UPDATE provider_connections SET base_url = 'https://x.example' WHERE id = :pid"), pid
                )
                assert moved.rowcount == 0, "another account changed the connection"
    finally:
        await engine.dispose()


async def test_a_new_account_chats_through_a_default_alias_of_its_own(models: Models) -> None:
    # As the dev stack does: `default` is bound to the fake OpenAI-compatible model.
    async def made(tenant: str) -> int:
        fake = "https://fake-openai.example/v1"
        return await seed_account(models.engine, tenant, install_tenant="local", fake_openai_url=fake, install=None)

    seen: list[str] = []
    app = create_models_app(models.engine, upstream=_upstream(seen), account_models=made)
    hooks = {"response": [response_checker(app)]}
    new, never = f"t_{uuid4().hex[:8]}", f"t_{uuid4().hex[:8]}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://m", event_hooks=hooks
    ) as client:
        on_app = Models(client, models.engine, app)
        _, secret = await on_app.key(budget="5")
        # As platform-service's relay delivers the event for the account's first team.
        token = mint_service_token(
            dev_service_signer(), service="platform", audience="models", tenant_id=new, team_id="team_ops",
            scopes=["settings:manage"],
        )  # fmt: skip
        event = {"name": TEAM_CREATED, "key": f"team_ops:{new}", "teamId": "team_ops"}
        for _ in range(2):  # delivery is at least once
            r = await client.post("/v1/platform-events", json=event, headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200 and r.json()["data"]["handled"], r.text
        versions = await client.get("/v1/models/aliases/default/versions", headers=service_as(new))
        assert versions.status_code == 200, versions.text
        held = [v["providerId"] for v in versions.json()["data"]["data"]]
        assert held == [connection_id(OPENAI_LOCAL, new, "local")], f"the new account's default is not its own: {held}"
        assert (await on_app.complete(secret, alias="default", **{"X-Tenant-Id": new})).status_code == 200
        assert seen == ["fake-openai.example"]
        # An account that never got its models finds no default: an error, never another account's.
        refused = await on_app.complete(secret, alias="default", **{"X-Tenant-Id": never})
        assert (refused.status_code, refused.json()["error"]["code"]) == (404, "alias_not_found"), refused.text
