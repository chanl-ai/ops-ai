"""The MCP address's platform operations (list and install templates, skills as prompts), driven by the official SDK's
client against a fake agents-service: one test per way a person could reach what their role does not give them, a
call could go unlogged, or a failure could break the protocol instead of answering."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
import httpx2
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp_types import Implementation
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_access.catalogue import Grant, encode_grid
from ops_identity import Auth, Identity, Principal, service_signer
from ops_service_kit.settings import Settings
from ops_tools import mcp_server
from ops_tools.mcp_tools import PAGE, PlatformTools
from ops_tools.modules.seed import load
from ops_tools.store.calls import gateway_calls
from ops_tools.store.modules import ModuleStore

from .conftest import Api, build_app, no_keys, opa_client
from .fake_mcp import tools as fake_tools
from .fake_upstream import ENDPOINT, HOST, fake_bank

TEAM = "team_lending"
RUN: list[Grant] = [("tools", "run", "all"), ("tools", "view", "all")]
# Each person's grid in the team: who may run tools, read skills, create skills and decide reviews.
GRIDS: dict[str, list[Grant]] = {
    "viewer": [("tools", "view", "all"), ("skills", "view", "all")],
    # Their own approver, so an install passes the gateway and reaches agents-service.
    "runner": [*RUN, ("skills", "view", "all"), ("reviews", "decide", "all")],
    "maker": [*RUN, ("skills", "view", "all"), ("skills", "create", "all")],
    "blind": RUN,
}


def _person(who: str, tenant: str) -> Principal:
    email = f"{who}@bank.test"
    return Principal(
        kind="person",
        sub=email,
        email=email,
        name=who,
        tenant_id=tenant,
        team_id=TEAM,
        team_ids=[TEAM],
        roles={TEAM: who},
        scopes=[],
        auth_method="session",
        access={TEAM: [who]},
        grids={who: encode_grid(GRIDS[who])},
        policies={"requesterMayDecide": True},
    )


def _content(result: Any) -> dict[str, Any]:
    content: dict[str, Any] = result.structured_content or {}
    return content


class AskerMayDecide:
    """The tenant's requesterMayDecide, on: a person holding reviews.decide approves their own write."""

    async def allowed(self, _tenant: str) -> bool:
        return True


async def _nobody(_key: str) -> None:
    return None


class People(Identity):
    """Platform-service's sign-in, answered from GRIDS: the bearer `ok_<who>` names the person (the ok_ prefix opens an
    address with no public sign-in URL, as an API key does)."""

    def __init__(self, tenant: str, **kw: Any) -> None:
        super().__init__(**kw)
        self.tenant = tenant

    async def bearer(self, authorization: str | None, team: str | None = None, *, resource: str | None = None) -> Any:
        return _person(str(authorization).split()[-1].removeprefix("ok_"), self.tenant)


def _scopes(request: Request) -> list[str]:
    token = request.headers["authorization"].split()[-1]
    part = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    return list(claims.get("scopes") or str(claims.get("scope") or "").split())


class Agents:
    """agents-service as the operations call it: it decides by the scopes the service token carries, as `can` does."""

    def __init__(self, skills: int = 2) -> None:
        self.app = FastAPI()
        self.made: list[str] = []
        self.list_calls = 0
        rows: list[dict[str, Any]] = [
            {"id": f"sk_{n}", "slug": f"skill-{n}", "name": f"Skill {n}", "useWhen": "", "inputs": []}
            for n in range(skills)
        ]

        @self.app.get("/v1/templates")
        async def templates(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            return {"data": [{"id": "doc-coauthoring", "kind": "skill"}]}

        @self.app.post("/v1/resources/{resource}/copies")
        async def install(resource: str, request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            if "skills:create" not in _scopes(request):
                return JSONResponse({"error": {"code": "role_required", "message": "no skills:create"}}, 403)
            self.made.append(resource)
            return JSONResponse({"data": {"copy": {"recordId": "sk_new"}}}, 201)

        @self.app.get("/v1/skills")
        async def skills_page(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            if "skills:view" not in _scopes(request):
                return JSONResponse({"error": {"code": "role_required", "message": "no skills:view"}}, 403)
            self.list_calls += 1
            n, size = int(request.query_params["page"]), int(request.query_params["pageSize"])
            return {"data": {"data": rows[(n - 1) * size : n * size], "total": len(rows)}}


class Stack:
    def __init__(self, app: Any, agents: Agents, engine: AsyncEngine, tenant: str) -> None:
        self.app, self.agents, self.engine, self.tenant = app, agents, engine, tenant

    def session(self, who: str) -> Any:
        http = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=self.app),
            base_url="http://tools",
            headers={"Authorization": f"Bearer ok_{who}"},
        )
        return Client(
            streamable_http_client(f"http://tools/mcp/{TEAM}", http_client=http),
            client_info=Implementation(name="pytest-assistant", version="1.0"),
            cache=None,
        )

    async def rows(self, tool: str) -> list[dict[str, Any]]:
        async with self.engine.connect() as c:
            q = sa.select(gateway_calls).where(gateway_calls.c.tenant_id == self.tenant, gateway_calls.c.tool == tool)
            return [dict(r) for r in (await c.execute(q)).mappings()]


async def _stack(
    *,
    engine: AsyncEngine,
    seed: dict[str, Any],
    tenant: str,
    catalog: list[dict[str, Any]],
    monkeypatch: Any,
    agents: Agents,
) -> AsyncIterator[Stack]:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog)
    fake, _ = fake_bank(fake_tools())
    settings = Settings()
    dev = Auth.for_dev(settings, audience="tools", name="dev", email="dev", tenant_id=tenant)
    identity = People(
        tenant,
        audience="tools",
        jwks=no_keys,
        introspect=_nobody,
        dev_user=dev.identity.dev_user,
        services=dev.services,
    )
    to_agents = httpx.AsyncClient(transport=httpx.ASGITransport(app=agents.app))
    platform = PlatformTools({"agents": "http://agents"}, service_signer(settings), to_agents)

    def platform_tools(_s: Settings, _agents: str | None = None) -> PlatformTools:
        return platform

    monkeypatch.setattr(mcp_server, "platform_tools", platform_tools)
    async with opa_client() as opa, httpx.AsyncClient(transport=httpx.ASGITransport(app=fake)) as upstream:
        app = build_app(
            engine,
            seed,
            tenant,
            opa=opa,
            upstream=upstream,
            auth=Auth(identity, dev.services),
            mcp=True,
            requester_policy=AskerMayDecide(),
        )
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tools") as rest:
            api = Api(rest, tenant)
            await rest.post("/v1/egress/hosts", json={"value": HOST})
            ops: list[dict[str, Any]] = [
                {"name": "lookup_case", "description": "Find a case", "access": "read", "group": "t", "input": []}
            ]
            source = {"kind": "mcp", "url": f"{ENDPOINT}/mcp"}
            r = await api.call(
                "POST", "/mod_document_service/operations/import", json={"source": source, "operations": ops}
            )
            assert r.status_code == 200, r.text
            store = ModuleStore(engine)
            m = await store.get(tenant, "mod_document_service")
            assert m is not None
            await store.put({**m, "status": "published"}, expected_revision=m["revision"])
            yield Stack(app, agents, engine, tenant)
    await to_agents.aclose()


@pytest.fixture
async def stack(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], monkeypatch: Any
) -> AsyncIterator[Stack]:
    async for s in _stack(
        engine=engine, seed=seed, tenant=tenant, catalog=catalog_tools, monkeypatch=monkeypatch, agents=Agents()
    ):
        yield s


@pytest.fixture
async def many(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]], monkeypatch: Any
) -> AsyncIterator[Stack]:
    async for s in _stack(
        engine=engine,
        seed=seed,
        tenant=tenant,
        catalog=catalog_tools,
        monkeypatch=monkeypatch,
        agents=Agents(skills=PAGE + 1),
    ):
        yield s


async def test_a_member_without_tools_run_runs_neither_a_team_tool_nor_a_platform_one(stack: Stack) -> None:
    async with stack.app.router.lifespan_context(stack.app), stack.session("viewer") as c:
        team = await c.call_tool("lookup_case", {})
        platform = await c.call_tool("list_templates", {})
    assert team.is_error and platform.is_error, (team, platform)
    assert _content(team).get("code") == "role_required", team
    assert _content(platform).get("code") == "role_required", platform


async def test_tools_run_without_the_create_right_cannot_install_a_template(stack: Stack) -> None:
    """agents-service trusts the scopes the token carries, so only the person's own cells may be sent: a role with
    tools:run and no skills:create is refused there, and nothing is made."""
    async with stack.app.router.lifespan_context(stack.app), stack.session("runner") as c:
        out = await c.call_tool("install_template", {"resource": "plugin:opsai.starters:doc-coauthoring"})
    error: dict[str, Any] = _content(out).get("error") or {}
    assert error.get("code") == "role_required", out
    assert stack.agents.made == []


async def test_template_calls_are_gateway_calls_and_an_install_is_not_held(stack: Stack) -> None:
    """An install only makes a draft that still needs its publish review, so it runs for a person who may create skills
    without being their own approver; it keeps its call log row. Every other MCP write still waits
    (test_mcp_server.py test_a_write_over_mcp_waits_for_a_person_even_when_declared_to_run_at_once)."""
    async with stack.app.router.lifespan_context(stack.app), stack.session("maker") as c:
        listed = await c.call_tool("list_templates", {"kind": "skill"})
        made = await c.call_tool("install_template", {"resource": "plugin:opsai.starters:doc-coauthoring"})
    assert not listed.is_error and _content(listed).get("templates"), listed
    [row] = await stack.rows("list_templates")
    assert (row["channel"], row["outcome"], row["sub"]) == ("mcp", "ok", "maker@bank.test")
    assert not made.is_error, made
    assert stack.agents.made == ["plugin:opsai.starters:doc-coauthoring"]
    [installed] = await stack.rows("install_template")
    assert (installed["channel"], installed["outcome"]) == ("mcp", "ok")


async def test_prompts_page_through_every_skill_and_a_person_who_cannot_read_skills_gets_none(many: Stack) -> None:
    async with many.app.router.lifespan_context(many.app), many.session("runner") as c:
        prompts = (await c.list_prompts()).prompts
    assert len(prompts) == PAGE + 1, len(prompts)
    assert many.agents.list_calls == 2, "one list call per page, none per skill"
    assert [r["outcome"] for r in await many.rows("prompts/list")] == ["ok"]
    async with many.app.router.lifespan_context(many.app), many.session("blind") as c:
        none = (await c.list_prompts()).prompts
    assert none == []
