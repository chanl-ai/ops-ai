"""Installing a plugin's agent as a team's own copy (c-590), through the real routes, by failure mode: the list shows a
template the team cannot install, or hides which ones it already holds; an install skips a check the agent create
route makes, so a copy grants a tool the team cannot call, cites a knowledge base it does not have, or runs on a model
alias nobody serves; a second install of the same version makes a second copy; a deleted copy blocks the template for
good; a copy lands live without review; and an install of a template whose plugin is off for the team, or of a version
it does not ship, makes something anyway.

tools-service is faked at the client agents-service calls it through: it answers the templates a team sees, as
GET /v1/plugin-templates does (tools-service's own tests prove that answer). The agent's tools and knowledge come from
the fixture catalogue, as on create."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic_ai.models.test import TestModel
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities.tool_directory import OperationRef
from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_service_kit.settings import Settings

from ..conftest import SEED, FakeGraphModels
from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app

OPS = person("james", "team_ops", "builder")
VIEWER = person("vera", "team_ops", "viewer")
SOURCE = "plugin:test.templates"
TOOLS = ["templates_get_case", "templates_close_case"]

AGENT = {
    "source": SOURCE,
    "plugin": {"id": "test.templates", "title": "Case desk", "version": "0.2.0"},
    "kind": "agent",
    "id": "case-helper",
    "version": 2,
    "title": "Case helper",
    "requires": {"tools": TOOLS, "bind": [{"knowledge_base": "Case articles"}, {"model_alias": "chat"}]},
    "body": {
        "name": "Case helper",
        "role": "Reads a case, explains it, and closes it when the person asks",
        "channels": ["chat"],
        "instructions": "Read the case with get_case.",
    },
    "digest": "a" * 64,
}


class Templates:
    """tools-service's template list as the acting team sees it; empty while the plugin is off for the team."""

    def __init__(self, listed: list[dict[str, Any]]) -> None:
        self.listed = listed
        self.asked: list[dict[str, Any] | None] = []

    async def get(self, path: str, params: dict[str, Any] | None = None, team: str | None = None, **_: Any) -> Any:
        assert path == "/v1/plugin-templates"
        # The call names the acting team: tools-service refuses a service token that names none.
        assert team in {"team_ops", "team_lending"}, team
        self.asked.append(params)
        kind = (params or {}).get("kind")
        return [t for t in self.listed if kind in (None, t["kind"])]


class Directory:
    """The operations tools-service offers the team: the plugin's two while it is on."""

    def __init__(self, names: list[str]) -> None:
        self.names = names

    async def operations(self) -> list[OperationRef]:
        return [
            OperationRef(
                name=n,
                description=n,
                access="read",
                input_schema={"type": "object"},
                requires_approval=False,
                module_id="mod_plugin_templates",
                module_name="Case desk",
            )
            for n in self.names
        ]


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


def wire(client: AsyncClient, listed: list[dict[str, Any]], tools: list[str] = TOOLS) -> Templates:
    rt = client._transport.app.state.runtime  # type: ignore[attr-defined]
    templates = Templates(listed)
    rt.tool_reviews = SimpleNamespace(tools=templates)
    rt.tool_directory = Directory(tools)
    return templates


async def install(client: AsyncClient, body: dict[str, Any] | None = None, *, tid: str = "case-helper") -> Any:
    return await client.post(f"/v1/templates/{SOURCE}/{tid}/install", json=body or {}, headers=OPS)


async def test_the_list_shows_the_teams_templates_and_which_it_holds(client: AsyncClient) -> None:
    wire(client, [AGENT])
    before = ok(await client.get("/v1/templates", params={"kind": "agent"}, headers=OPS))
    assert [(t["id"], t["installed"]) for t in before] == [
        ("case-helper", {"copies": 0, "version": None, "newerAvailable": False, "changed": False})
    ]
    ok(await install(client, {"knowledgeBases": ["kb_support"]}), 201)
    after = ok(await client.get("/v1/templates", params={"kind": "agent"}, headers=OPS))
    assert after[0]["installed"] == {"copies": 1, "version": 2, "newerAvailable": False, "changed": False}
    # A newer version shipped by the plugin is offered, and the copy stays as it is.
    wire(client, [AGENT | {"version": 3}])
    newer = ok(await client.get("/v1/templates", params={"kind": "agent"}, headers=OPS))
    assert newer[0]["installed"] == {"copies": 1, "version": 2, "newerAvailable": True, "changed": False}


async def test_an_installed_agent_is_the_teams_draft_through_the_create_checks(client: AsyncClient) -> None:
    wire(client, [AGENT])
    made = ok(await install(client, {"knowledgeBases": ["kb_support"], "name": "Ops case helper"}), 201)
    assert made["created"] is True and made["copy"]["kind"] == "agent" and made["copy"]["version"] == 2
    agent = ok(await client.get(f"/v1/agents/{made['copy']['recordId']}", headers=OPS))
    assert agent["name"] == "Ops case helper" and agent["teamId"] == "team_ops"
    assert agent["availability"] != "published" and agent["toolIds"] == TOOLS and agent["collections"] == ["kb_support"]
    # The copy answers nothing about where it came from: the template list does.
    assert ("copiedFrom" not in agent and "templateId" not in agent) or agent["templateId"] is None


async def test_the_same_version_again_answers_the_copy_and_a_deleted_copy_lets_a_new_one_in(
    client: AsyncClient,
) -> None:
    wire(client, [AGENT])
    first = ok(await install(client), 201)["copy"]
    again = ok(await install(client), 200)
    assert again["created"] is False and again["copy"]["recordId"] == first["recordId"]
    gone = await client.delete(f"/v1/agents/{first['recordId']}", headers=OPS)
    assert gone.status_code == 204, gone.text
    fresh = ok(await install(client), 201)["copy"]
    assert fresh["recordId"] != first["recordId"]


async def test_a_wrong_binding_or_tool_is_refused_as_create_refuses_it_and_nothing_is_made(
    client: AsyncClient,
) -> None:
    wire(client, [AGENT], tools=TOOLS[:1])
    no_tool = await install(client)
    assert no_tool.status_code == 400 and no_tool.json()["error"]["code"] == "unknown_tool", no_tool.text
    wire(client, [AGENT])
    no_kb = await install(client, {"knowledgeBases": ["kb_nobody"]})
    assert no_kb.status_code == 422 and no_kb.json()["error"]["code"] == "unknown_knowledge_base", no_kb.text
    no_alias = await install(client, {"modelAlias": "nobody-serves-this"})
    assert no_alias.status_code == 422 and no_alias.json()["error"]["code"] == "unknown_model_alias", no_alias.text
    listed = ok(await client.get("/v1/agents", params={"search": "Case helper"}, headers=OPS))
    assert listed["data"] == []


async def test_a_template_not_listed_for_the_team_or_a_version_it_does_not_ship_is_not_found(
    client: AsyncClient,
) -> None:
    wire(client, [])  # the plugin is off for the team, so tools-service lists nothing
    off = await install(client)
    assert off.status_code == 404 and off.json()["error"]["code"] == "template_not_found", off.text
    wire(client, [AGENT])
    old = await install(client, {"version": 1})
    assert old.status_code == 404 and old.json()["error"]["code"] == "template_version_not_found", old.text


async def test_a_viewer_cannot_install(client: AsyncClient) -> None:
    wire(client, [AGENT])
    r = await client.post(f"/v1/templates/{SOURCE}/case-helper/install", json={}, headers=VIEWER)
    assert r.status_code == 403, r.text


async def test_the_install_needs_says_what_is_left_to_bind(client: AsyncClient) -> None:
    wire(client, [AGENT])
    made = ok(await install(client), 201)
    assert made["needs"] == [
        {"knowledgeBase": "Case articles"},
        {"modelAlias": "chat"},
    ]


async def test_a_session_acting_in_no_team_cannot_install() -> None:
    """A dev session acts across teams, so a copy it made would be no team's and every team would see it."""
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    app = create_app(
        Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED),
        model=TestModel(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
    )
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(app.router.lifespan_context(app))
        client = await stack.enter_async_context(AsyncClient(transport=ASGITransport(app=app), base_url="http://t"))
        wire(client, [AGENT])
        r = await client.post(f"/v1/templates/{SOURCE}/case-helper/install", json={}, headers={"X-Team-Id": "team_ops"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "team_required", r.text


async def test_deleting_a_copy_marks_it_removed_and_a_changed_template_shows_as_changed(client: AsyncClient) -> None:
    wire(client, [AGENT])
    aid = ok(await install(client), 201)["copy"]["recordId"]
    # The plugin ships a changed body at the same version: the copy was made from the old one.
    wire(client, [AGENT | {"digest": "b" * 64}])
    changed = ok(await client.get("/v1/templates", params={"kind": "agent"}, headers=OPS))[0]["installed"]
    assert changed["copies"] == 1 and changed["changed"] is True, changed
    gone = await client.delete(f"/v1/agents/{aid}", headers=OPS)
    assert gone.status_code == 204, gone.text
    # The delete marks the copy removed at once, before any reinstall looks.
    after = ok(await client.get("/v1/templates", params={"kind": "agent"}, headers=OPS))[0]["installed"]
    assert after["copies"] == 0, after
