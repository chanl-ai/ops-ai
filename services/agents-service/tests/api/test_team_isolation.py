"""A team is the data boundary (c-407): a person outside the team that owns an agent, skill, guardrail or widget does
not see it in a list, and reading it by id or through a sub-route answers 404, as a case or a run does. Inside the
team the roles grid decides. Each failure mode drives the real routes with tokens minted as platform-service mints them:

- the list shows another team's record (agents, skills, guardrails, widgets, case types);
- a read by id answers 200;
- a sub-route of the record answers 200;
- the owner lookup that refuses a chat stops seeing the agent, so an outsider's chat is let through;
- a reviewer of the owning team who acts in another team can no longer publish what they approve.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store.tables import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle import definition
from tests.engine.test_lifecycle_rights import (
    BUILDER,
    PLATFORM,
    TENANT,
    introspect,
    jwks,
    person,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
)

from .test_widget_registry import LIMIT_CARD
from .test_write_roles import reviewed_stack

OUTSIDER = person("omar", "team_fraud", "admin")
RULE: dict[str, Any] = {"name": "No tax advice", "topics": ["tax advice"], "message": "I can't give tax advice."}
SKILL: dict[str, Any] = {
    "name": "Address change",
    "useWhen": "The customer asks to change their postal address.",
    "instructions": "Confirm the customer, then record the new address.",
    "ownerTeam": "Retail",
}


def _data(r: Any) -> Any:
    assert r.status_code < 300, r.text
    return r.json()["data"]


def _ids(listed: Any) -> set[str]:
    rows = cast(list[dict[str, Any]], listed["data"] if isinstance(listed, dict) else listed)
    return {str(r.get("id") or r.get("widgetId")) for r in rows}


async def _team_ops_agent(c: AsyncClient) -> str:
    return str(
        _data(await c.post("/v1/agents", json={"name": "Payee checker", "role": "Checks payees"}, headers=BUILDER))[
            "id"
        ]
    )


async def test_a_list_leaves_out_another_teams_records(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    made = {
        "/v1/agents": await _team_ops_agent(c),
        "/v1/skills": str(_data(await c.post("/v1/skills", json=SKILL, headers=BUILDER))["id"]),
        "/v1/guardrails": str(_data(await c.post("/v1/guardrails", json=RULE, headers=BUILDER))["id"]),
        "/v1/widgets": str(_data(await c.post("/v1/widgets", json=LIMIT_CARD, headers=BUILDER))["widgetId"]),
    }
    for path, made_id in made.items():
        assert made_id in _ids(_data(await c.get(path, headers=BUILDER))), f"{path}: the owner does not see it"
        assert made_id not in _ids(_data(await c.get(path, headers=OUTSIDER))), f"{path}: another team sees it"


@pytest.mark.parametrize("kind", ["agents", "skills", "guardrails", "widgets"])
async def test_another_teams_record_answers_404_by_id(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
    kind: str,
) -> None:
    c, _ = stack
    body = {"agents": {"name": "Payee checker", "role": "Checks payees"}, "skills": SKILL, "guardrails": RULE}
    made = _data(await c.post(f"/v1/{kind}", json=body.get(kind, LIMIT_CARD), headers=BUILDER))
    path = f"/v1/{kind}/{made.get('id') or made.get('widgetId')}"
    assert (await c.get(path, headers=BUILDER)).status_code == 200
    r = await c.get(path, headers=OUTSIDER)
    assert r.status_code == 404, r.text


async def test_another_teams_case_type_is_not_listed_and_answers_404(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    # A team's copy of a seeded type is its own; the seeded type itself is a platform record every team reads.
    c, _ = stack
    copy = {"id": "ops_complaint", "copyOf": {"id": "complaint"}}
    assert (await c.post("/v1/case-types", json=copy, headers=BUILDER)).status_code == 201
    assert "ops_complaint" in _ids(_data(await c.get("/v1/case-types", headers=BUILDER)))
    theirs = _ids(_data(await c.get("/v1/case-types", headers=OUTSIDER)))
    assert "ops_complaint" not in theirs and "complaint" in theirs
    r = await c.get("/v1/case-types/ops_complaint", headers=OUTSIDER)
    assert r.status_code == 404, r.text


@pytest.mark.parametrize("sub", ["versions", "live", "skills"])
async def test_another_teams_agent_answers_404_on_its_sub_routes(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
    sub: str,
) -> None:
    c, _ = stack
    agent = await _team_ops_agent(c)
    assert (await c.get(f"/v1/agents/{agent}/{sub}", headers=BUILDER)).status_code == 200
    r = await c.get(f"/v1/agents/{agent}/{sub}", headers=OUTSIDER)
    assert r.status_code == 404, r.text


async def test_an_outsider_cannot_chat_with_another_teams_agent(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    # A seeded agent is live and owned by team_ops; the outsider is an admin of another team.
    c, _ = stack
    listed = _data(await c.get("/v1/agents", headers=BUILDER))["data"]
    live = next(a for a in listed if a["teamId"] == "team_ops" and a["publishedVersion"] is not None)
    assert (
        await c.post("/v1/chat/threads", json={"agentId": live["id"], "kbIds": []}, headers=BUILDER)
    ).status_code < 300
    r = await c.post("/v1/chat/threads", json={"agentId": live["id"], "kbIds": []}, headers=OUTSIDER)
    assert r.status_code in (403, 404), r.text


def _two_teams(sub: str, acting: str, roles: dict[str, str]) -> dict[str, str]:
    claims = {
        "sub": sub,
        "email": f"{sub}@harborpine.example",
        "name": sub,
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": list(roles),
        "roles": roles,
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": acting}


async def test_a_reviewer_acting_in_another_team_publishes_the_agent_they_approve() -> None:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(engine_metadata.create_all)
    async with reviewed_stack(engine) as c:
        agent = await _team_ops_agent(c)
        asked = _data(await c.post(f"/v1/agents/{agent}/publish-requests", json={"version": 1}, headers=BUILDER))
        # A reviewer of team_ops whose console has team_fraud selected.
        maya = _two_teams("maya", "team_fraud", {"team_ops": "approver", "team_fraud": "viewer"})
        r = await c.post(f"/v1/publish-requests/{asked['id']}/decision", json={"decision": "approved"}, headers=maya)
        assert r.status_code == 200, r.text
        assert _data(await c.get(f"/v1/agents/{agent}", headers=BUILDER))["publishedVersion"] == 1
    await engine.dispose()


async def test_a_workflow_definition_is_listed_with_its_team_so_it_can_be_granted() -> None:
    # A v2 workflow is granted tool access as a v1 one is (c-433): tools-service finds it and its team here.
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    services = ServiceAuth(
        audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes
    )
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0, services=services), services
    )
    app = create_app(
        settings,
        model=scripted_model(),
        engine=engine,
        checkpointer=InMemorySaver(),
        graph_models=FakeGraphModels(),
        auth=auth,
        knowledge=fixture_knowledge(),
    )
    wid = f"c433_{uuid4().hex[:6]}"
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        saved = await c.post("/v1/workflows/definitions", json={"definition": definition(wid)}, headers=BUILDER)
        assert saved.status_code == 201, saved.text
        asked = await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=BUILDER)
        assert asked.status_code < 300, asked.text
        token = mint_service_token(
            dev_service_signer(), service="tools", audience="agents", tenant_id=TENANT, scopes=["workflows:view"]
        )
        r = await c.get("/v1/workflow-refs", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        rows = {w["id"]: w for w in r.json()["data"]}
        assert rows.get(wid, {}).get("teamId") == "team_ops", r.text[:300]
    await engine.dispose()


async def test_the_chat_agent_picker_offers_only_the_teams_agents(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    # The live catalogue holds every team's agents; the picker read it whole, so another team's showed (c-407).
    c, _ = stack
    mine = {a["id"] for a in _data(await c.get("/chat/agents", headers=BUILDER))}
    assert mine, "the owning team's live agents are offered"
    theirs = {a["id"] for a in _data(await c.get("/chat/agents", headers=OUTSIDER))}
    assert not mine & theirs, sorted(mine & theirs)
