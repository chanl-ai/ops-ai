"""The MCP adapter (c-356), driven by the official SDK's client in process: one test per way an assistant could list or
run what its key should not, run a write without a person, or go unseen in the call log."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import httpx2
import pytest
import sqlalchemy as sa
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import Auth, Identity
from ops_service_kit.settings import Settings
from ops_tools.modules.seed import load
from ops_tools.store.calls import gateway_calls
from ops_tools.store.modules import ModuleStore

from .conftest import Api, build_app, no_keys, opa_client
from .fake_mcp import tools as fake_tools
from .fake_upstream import ENDPOINT, HOST, fake_bank

MCP_SOURCE = {"kind": "mcp", "url": f"{ENDPOINT}/mcp"}
# Keys platform-service would introspect: one of the module's owning team, one of another team.
KEYS = {"ok_lending": "team_lending", "ok_cards": "team_cards"}


def _introspect(tenant: str) -> Any:
    async def introspect(key: str) -> dict[str, Any] | None:
        team = KEYS.get(key)
        if team is None:
            return None
        return {
            "sub": f"key:{key}",
            "email": "",
            "name": f"{team} key",
            "tenantId": tenant,
            "teamId": team,
            "scopes": ["read", "write"],
            "apiKey": {"id": key},
        }

    return introspect


class Stack:
    def __init__(self, app: Any, api: Api, received: list[dict[str, Any]], engine: AsyncEngine) -> None:
        self.app, self.api, self.received, self.engine = app, api, received, engine

    def running(self) -> Any:
        """The gateway's lifespan (OPA's policy, the SDK's session manager), entered in the test's own task: the
        manager's task group must be left in the task that entered it, which a fixture's teardown is not."""
        return self.app.router.lifespan_context(self.app)

    def http(self, key: str | None) -> httpx2.AsyncClient:
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        return httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app), base_url="http://tools", headers=headers
        )

    def client(self, http: httpx2.AsyncClient, path: str) -> Client:
        url = f"http://tools{path}"
        return Client(
            streamable_http_client(url, http_client=http),
            client_info=Implementation(name="pytest-assistant", version="1.0"),
            cache=None,
        )

    async def rows(self, tool: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            q = sa.select(gateway_calls).where(
                gateway_calls.c.tenant_id == self.api.tenant, gateway_calls.c.tool == tool
            )
            return [dict(r) for r in (await c.execute(q)).mappings()]


@pytest.fixture
async def stack(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> AsyncIterator[Stack]:
    """The fake bank's MCP server imported into Lending Ops' module (lookup_case a read, close_case a write declared to
    run at once), published, behind a gateway whose API keys platform-service would introspect."""
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    fake, received = fake_bank(fake_tools())
    settings = Settings()
    me = seed["currentUser"]
    dev = Auth.for_dev(settings, audience="tools", name=me, email=me, tenant_id=tenant)
    identity = Identity(
        audience="tools",
        jwks=no_keys,
        introspect=_introspect(tenant),
        dev_user=dev.identity.dev_user,
        services=dev.services,
    )
    auth = Auth(identity, dev.services)
    async with opa_client() as opa, httpx.AsyncClient(transport=httpx.ASGITransport(app=fake)) as upstream:
        app = build_app(engine, seed, tenant, opa=opa, upstream=upstream, auth=auth, mcp=True)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as rest:
            api = Api(rest, tenant)
            await rest.post("/v1/egress/hosts", json={"value": HOST})
            ops: list[dict[str, Any]] = [
                {"name": "lookup_case", "description": "Find a case", "access": "read", "group": "t", "input": []},
                {"name": "close_case", "description": "Close a case", "access": "write", "group": "t", "input": []},
            ]
            r = await api.call(
                "POST", "/mod_document_service/operations/import", json={"source": MCP_SOURCE, "operations": ops}
            )
            assert r.status_code == 200, r.text
            store = ModuleStore(engine)
            m = await store.get(tenant, "mod_document_service")
            assert m is not None
            for op in m["operations"]:
                if op["name"] == "close_case":
                    op["requires_approval"] = False
            await store.put({**m, "status": "published"}, expected_revision=m["revision"])
            yield Stack(app, api, received, engine)


async def test_a_key_lists_only_its_teams_reads_with_schemas(stack: Stack) -> None:
    async with stack.running(), stack.http("ok_lending") as http, stack.client(http, "/mcp/test/team_lending") as c:
        listed = {t.name: t for t in (await c.list_tools()).tools}
    assert "lookup_case" in listed
    assert "close_case" not in listed, "slice 1 lists no writes"
    assert all(t.annotations and t.annotations.read_only_hint for t in listed.values())
    assert listed["lookup_case"].input_schema["type"] == "object"
    async with stack.running(), stack.http("ok_cards") as http, stack.client(http, "/mcp/test/team_cards") as c:
        other = {t.name for t in (await c.list_tools()).tools}
    assert "lookup_case" not in other, "another team's key does not see Lending Ops' module"


async def test_a_read_runs_through_the_gateway_and_the_log_names_mcp_and_the_client(stack: Stack) -> None:
    async with stack.running(), stack.http("ok_lending") as http, stack.client(http, "/mcp/test/team_lending") as c:
        result = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
    assert result.is_error is False, result
    assert result.structured_content is not None
    assert result.structured_content["arguments"] == {"caseId": "CASE-4112"}
    [row] = await stack.rows("lookup_case")
    assert (row["channel"], row["client_name"], row["sub"], row["outcome"]) == (
        "mcp",
        "pytest-assistant",
        "key:ok_lending",
        "ok",
    )
    assert row["environment"] == "test"


async def test_a_write_over_mcp_waits_for_a_person_even_when_declared_to_run_at_once(stack: Stack) -> None:
    async with stack.running(), stack.http("ok_lending") as http, stack.client(http, "/mcp/test/team_lending") as c:
        result = await c.call_tool("close_case", {"caseId": "CASE-4112"})
    assert result.is_error is True
    assert not [x for x in stack.received if "closeCase" in str(x.get("body"))], "the bank received nothing"
    [row] = await stack.rows("close_case")
    assert (row["channel"], row["decision"], row["outcome"]) == ("mcp", "deny", "refused")


async def test_a_tool_of_a_module_outside_the_team_is_refused_and_logged(stack: Stack) -> None:
    async with stack.running(), stack.http("ok_cards") as http, stack.client(http, "/mcp/test/team_cards") as c:
        result = await c.call_tool("lookup_case", {"caseId": "CASE-4112"})
    assert result.is_error is True and result.structured_content is not None
    # Another team's operation is not found (c-509); the refusal names no owner.
    assert result.structured_content["code"] == "gateway_refused"
    [row] = await stack.rows("lookup_case")
    assert (row["channel"], row["outcome"]) == ("mcp", "refused")


@pytest.mark.parametrize(
    ("key", "path", "status", "code"),
    [
        (None, "/mcp/test/team_lending", 401, "unauthorized"),
        ("ok_nobody", "/mcp/test/team_lending", 401, "unauthorized"),
        ("ok_lending", "/mcp/test/team_cards", 403, "team_forbidden"),
        ("ok_lending", "/mcp/production/team_lending", 403, "production_off"),
    ],
    ids=["no-key", "unknown-key", "other-team-url", "production"],
)
async def test_the_url_and_the_key_are_checked_before_the_protocol(
    stack: Stack, key: str | None, path: str, status: int, code: str
) -> None:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    async with stack.http(key) as http:
        r = await http.post(path, json=body, headers={"Accept": "application/json, text/event-stream"})
    assert (r.status_code, r.json()["error"]["code"]) == (status, code), r.text
    if status == 401:
        assert r.headers["www-authenticate"].startswith("Bearer")


async def test_a_key_holding_tools_run_cannot_use_the_test_console(stack: Stack) -> None:
    """The cell keys gained for MCP opens nothing else: the test console's reads are not logged or rate limited."""
    body: dict[str, Any] = {"operation": "lookup_case", "contextId": "owner", "target": "stub", "input": {}}
    r = await stack.api.client.post(
        "/v1/tool-modules/mod_document_service/test", json=body, headers={"Authorization": "Bearer ok_lending"}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (403, "role_required"), r.text
