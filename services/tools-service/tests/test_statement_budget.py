"""Every GET route of tools-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a route whose statements grow with the rows it shows, a route over its row, and a route that opens a
second transaction or checks out a second connection without its row saying so. Runs on PostgreSQL and SQL Server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_plugin_sdk.loader import discover
from ops_service_kit.settings import Settings
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check
from ops_store import isolation
from ops_store.database import open_database
from ops_tools.modules.tool_users import StaticToolUsers
from ops_tools.plugins.host import PluginHost
from ops_tools.plugins.templates import plugin_templates_router
from ops_tools.store import CallLog
from ops_tools.store.connections import ConnectionStore
from ops_tools.store.discoveries import Discoveries, FoundOperation
from ops_tools.store.egress import EgressStore
from ops_tools.store.mcp_links import LinkedTool, McpLinks
from ops_tools.store.modules import ModuleStore
from ops_tools.store.plugin_bindings import PluginBindings
from ops_tools.store.secrets import SecretStore

from .conftest import build_app, opa_client, service_headers, team_credential
from .test_plugin_templates import FakeCopies
from .test_plugin_versions import ID, V1
from .test_review_decisions import introspect, jwks, person
from .test_traffic import logged

BUDGETS = Path(__file__).parents[1] / "budgets.toml"
TEAM = "team_ops"
APP = f"plugin:{ID}"
TOOLS = [LinkedTool(name="lookup_case", title="Look up a case", kind="tool", access="read")]

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
async def app(database_url: str, seed: dict[str, Any]) -> AsyncIterator[FastAPI]:
    """tools-service on its own engine, whose statements and transactions the request line counts, signing people in
    with platform-service's tokens and serving the fields_desk plugin."""
    engine = open_database(database_url)
    settings = Settings()
    auth = Auth(
        Identity(audience="tools", jwks=jwks, introspect=introspect, key_cache_s=0),
        ServiceAuth(audience="tools", verifiers=service_verifiers(settings, "tools"), scopes=settings.service_scopes),
    )
    host = PluginHost(
        ModuleStore(engine),
        PluginBindings(engine),
        {},
        discover(found=[], folders=[str(V1)]),
        ConnectionStore(engine),
        versions=True,
    )
    users = StaticToolUsers({})
    app = build_app(engine, seed, "t_unused", opa=opa_client(), auth=auth, plugins=host, users=users)
    # As __main__ mounts it beside the plugin routes; agents-service's copies answer from memory.
    app.include_router(plugin_templates_router(host, FakeCopies()))
    yield app
    await engine.dispose()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as c:
        yield c


@pytest.fixture
def seed_team(database_url: str, client: httpx.AsyncClient) -> SeedTeam:
    """A new tenant whose team_ops admin has the plugin on with `n` accounts, and `n` secrets, links, listed hosts,
    custom apps each with the team's own OAuth client, and calls of the first seeded module's first operation; an
    agents-service token of the tenant calls the service-token routes."""

    async def make(n: int) -> Seeded:
        tenant = f"t_{uuid4().hex[:10]}"
        admin = person(tenant, "Priya Shah", {TEAM: "admin"})
        engine = open_database(database_url)
        at = datetime.now(UTC)
        with isolation.scope(tenant, TEAM):
            for i in range(n):
                await SecretStore(engine).create(tenant, TEAM, f"KEY_{i:03d}", f"sealed-{i}", actor="seed", at=at)
                await McpLinks(engine).create(
                    tenant, TEAM, slug=f"link-{i:03d}", name=f"Link {i:03d}", tools=TOOLS, by="s"
                )
                await EgressStore(engine).add(tenant, "host", f"h{i:03d}.example.com", actor="seed", note="", at=at)
        await engine.dispose()
        on = await client.put(
            f"/v1/apps/{APP}/team", json={"enabled": True, "credentials": {"token": "t-1"}}, headers=admin
        )
        assert on.status_code == 200, on.text
        for i in range(1, n):
            made = await client.post(
                f"/v1/apps/{APP}/accounts",
                json={"name": f"Desk {i:03d}", "credentials": {"token": f"t-{i}"}},
                headers=admin,
            )
            assert made.status_code in (200, 201), made.text
        accounts = (await client.get(f"/v1/apps/{APP}/accounts", headers=admin)).json()["data"]
        links = (await client.get("/v1/mcp-links", headers=admin)).json()["data"]["data"]
        module = (await client.get("/v1/tool-modules", headers=admin)).json()["data"]["data"][0]
        detail = (await client.get(f"/v1/tool-modules/{module['id']}", headers=admin)).json()["data"]
        op = detail["operations"][0]
        engine = open_database(database_url)
        calls = [
            await logged(CallLog(engine), module["id"], op["name"], outcome="ok", latency=5, at=at, tenant=tenant)
            for _ in range(n)
        ]
        # A discovery of `n` operations for the module, as POST /discover stores one for the admin.
        found: list[FoundOperation] = [
            {"name": f"op_{i:03d}", "description": "d", "access": "read", "method": "GET", "path": f"/v1/r/{i}",
             "group": f"g{i % 3}", "input": []}
            for i in range(n)
        ]  # fmt: skip
        with isolation.scope(tenant, TEAM):
            await Discoveries(engine).save(
                tenant_id=tenant, team_id=TEAM, id=f"disc_{n}", person="usr_priya", module_id=module["id"], meta={},
                operations=found, now=at, expires_at=at + timedelta(hours=1),
            )  # fmt: skip
        await engine.dispose()
        made_credentials: list[str] = []
        for i in range(n):
            new = {"name": f"Ledger {i:03d}", "authKind": "oauth2_auth_code"}
            custom = (await client.post("/v1/apps", json=new, headers=admin)).json()["data"]
            made_credentials.append(await team_credential(client, admin, custom["id"], f"ledger-{i}", "s"))
        ids = {
            "app_id": APP,
            "account_id": accounts[0]["id"],
            "link_id": links[0]["id"],
            "module_id": module["id"],
            "op_id": op["id"],
            "name": op["name"],
            "call_id": calls[0],
            "credential_id": made_credentials[0],
            "discovery_id": f"disc_{n}",
        }
        return Seeded(headers=admin, ids=ids, service_headers=service_headers(tenant))

    return make


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
