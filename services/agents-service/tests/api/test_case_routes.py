"""`/v1/cases` (c-128) through the routes with tokens minted as platform-service mints them, by failure mode: a
producer's retry opens a second case; another team reads, changes or links this team's case; an agent or workflow
closes a case; a member closes a case someone else opened; a field is cleared that the case cannot lack; a status
change leaves no timeline entry; a service with no cases scope opens one."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, dev_service_signer, mint_service_token, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, TENANT, VIEWER, introspect, jwks, person

OTHER_TEAM = person("omar", "team_fraud", "builder")
OTHER_VIEWER = person("ola", "team_ops", "viewer")
DISPUTE: dict[str, Any] = {"subject": "Card dispute", "priority": "high", "customerId": "C-1001", "customerName": "Ann"}


def service(name: str, scopes: list[str], team: str = "team_ops") -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(),
        service=name,
        audience="agents",
        tenant_id=TENANT,
        scopes=scopes,
        team_id=team,
        ttl_s=TEST_TOKEN_TTL_S,
    )
    return {"Authorization": f"Bearer {token}"}


WORKER = service("worker", ["cases:view", "cases:create", "cases:edit"])


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
        await conn.run_sync(engine_metadata.create_all)
    base = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    settings = base.model_copy(
        update={"service_scopes": {**base.service_scopes, "worker": ["cases:view", "cases:create", "cases:edit"]}}
    )
    services = ServiceAuth(
        audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes
    )
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0, services=services),
        ServiceAuth(audience="agents", verifiers=service_verifiers(settings, "agents")),
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
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client,
    ):
        yield client


async def opened(c: AsyncClient, who: dict[str, str] = VIEWER, **body: Any) -> dict[str, Any]:
    r = await c.post("/v1/cases", json={**DISPUTE, **body}, headers=who)
    assert r.status_code == 201, r.text
    return r.json()["data"]


async def test_a_producer_retry_finds_the_case_it_opened(c: AsyncClient) -> None:
    first = await opened(c, WORKER, producerKey="run_1")
    again = await c.post("/v1/cases", json={**DISPUTE, "producerKey": "run_1"}, headers=WORKER)
    assert again.status_code == 200 and again.json()["data"]["id"] == first["id"]
    listed = (await c.get("/v1/cases", headers=VIEWER)).json()["data"]
    assert [x["id"] for x in listed["data"]] == [first["id"]] and listed["pagination"]["total"] == 1


async def test_another_team_cannot_read_change_or_link_the_case(c: AsyncClient) -> None:
    case = await opened(c)
    theirs = await opened(c, OTHER_TEAM)
    assert (await c.get(f"/v1/cases/{case['id']}", headers=OTHER_TEAM)).status_code == 404
    patched = await c.patch(f"/v1/cases/{case['id']}", json={"priority": "low"}, headers=OTHER_TEAM)
    assert patched.status_code == 404
    linked = await c.post(f"/v1/cases/{case['id']}/links", json={"caseId": theirs["id"]}, headers=BUILDER)
    assert linked.status_code == 404
    assert (await c.get("/v1/cases", headers=OTHER_TEAM)).json()["data"]["pagination"]["total"] == 1


async def test_only_a_person_closes_a_case(c: AsyncClient) -> None:
    case = await opened(c, WORKER)
    resolved = await c.patch(f"/v1/cases/{case['id']}", json={"status": "resolved"}, headers=WORKER)
    assert resolved.status_code == 200, resolved.text
    closed = await c.patch(f"/v1/cases/{case['id']}", json={"status": "closed"}, headers=WORKER)
    assert closed.status_code == 422 and closed.json()["error"]["code"] == "person_required"
    by_admin = await c.patch(f"/v1/cases/{case['id']}", json={"status": "closed"}, headers=ADMIN)
    assert by_admin.status_code == 200 and by_admin.json()["data"]["status"] == "closed"


async def test_a_member_closes_only_the_cases_they_opened(c: AsyncClient) -> None:
    case = await opened(c)
    refused = await c.patch(f"/v1/cases/{case['id']}", json={"status": "closed"}, headers=OTHER_VIEWER)
    assert refused.status_code == 403
    worked = await c.patch(f"/v1/cases/{case['id']}", json={"assignee": "ola@northfield.example"}, headers=OTHER_VIEWER)
    assert worked.status_code == 200
    mine = await c.patch(f"/v1/cases/{case['id']}", json={"status": "closed"}, headers=VIEWER)
    assert mine.status_code == 200


async def test_a_required_field_cannot_be_cleared(c: AsyncClient) -> None:
    case = await opened(c)
    r = await c.patch(f"/v1/cases/{case['id']}", json={"subject": None}, headers=VIEWER)
    assert r.status_code == 422 and r.json()["error"]["code"] == "field_required"


async def test_changes_and_notes_are_timeline_entries(c: AsyncClient) -> None:
    case = await opened(c)
    await c.patch(f"/v1/cases/{case['id']}", json={"status": "waiting_on_customer"}, headers=VIEWER)
    r = await c.post(f"/v1/cases/{case['id']}/events", json={"text": "Asked for the receipt"}, headers=VIEWER)
    assert r.status_code == 201
    events = r.json()["data"]["events"]
    assert [e["kind"] for e in events] == ["opened", "field", "note"]
    assert events[1]["detail"] == {"field": "status", "before": "open", "after": "waiting_on_customer"}
    assert events[2]["by"] == "vera@northfield.example"
    assert r.json()["data"]["pausedSince"] is not None
    assert r.json()["data"]["resolutionLeftS"] is None


async def test_each_deadline_shows_the_time_left(c: AsyncClient) -> None:
    case = await opened(c, priority="urgent")
    assert 0 < case["responseLeftS"] <= 3600 and 3600 < case["resolutionLeftS"] <= 8 * 3600


async def test_a_service_without_the_cases_scope_opens_nothing(c: AsyncClient) -> None:
    r: httpx.Response = await c.post("/v1/cases", json=DISPUTE, headers=service("agents", ["files:view"]))
    assert r.status_code == 403


async def test_tools_service_opens_a_case_with_the_scopes_it_is_given(c: AsyncClient) -> None:
    """The open_case tool's call (c-219), with exactly what Settings.service_scopes gives tools-service."""
    tools = service("tools", ["cases:view", "cases:create"])
    r = await c.post("/v1/cases", json={**DISPUTE, "producerKey": "tool:gth_1:s3"}, headers=tools)
    assert r.status_code == 201, r.text
    assert r.json()["data"]["createdBy"] == "service:tools"


async def started_run(c: AsyncClient, who: dict[str, str], workflow: str) -> str:
    """A queued run of the basic workflow, saved as `workflow` in `who`'s team."""
    basic = (Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml").read_text()
    basic = basic.replace("id: refund_check", f"id: {workflow}", 1)
    created = await c.post("/v1/workflows/definitions", json={"yaml": basic}, headers=who)
    assert created.status_code == 201, created.text
    published = await c.post(f"/v1/workflows/definitions/{workflow}/publish-requests", json={}, headers=who)
    assert published.status_code == 201, published.text
    body = {"workflowId": workflow, "input": {"customerId": "C-1", "amount": 1}}
    r = await c.post("/v1/runs", json=body, headers=who)
    assert r.status_code == 202, r.text
    return str(r.json()["data"]["runId"])


async def test_a_case_names_only_runs_and_decisions_of_its_own_team(c: AsyncClient) -> None:
    # Naming another team's run on your case put that team's decisions, reasons and approvers on your timeline.
    theirs = await started_run(c, OTHER_TEAM, "fraud_check")
    ours = await started_run(c, BUILDER, "ops_check")
    case = await opened(c)
    url = f"/v1/cases/{case['id']}/events"
    foreign = await c.post(url, json={"kind": "run", "ref": theirs}, headers=VIEWER)
    decision = await c.post(url, json={"kind": "decision", "ref": f"{theirs}:review:1"}, headers=VIEWER)
    own = await c.post(url, json={"kind": "run", "ref": ours}, headers=VIEWER)
    assert foreign.status_code == 404 and decision.status_code == 404, (foreign.text, decision.text)
    assert own.status_code == 201, own.text


async def test_a_search_finds_cases_by_subject_customer_name_or_customer_id(c: AsyncClient) -> None:
    # Cases is paged on the server, so a search the console cannot do in the browser must happen here.
    levy = await opened(c, subject="Levy notice: Marcus Bell (NS-2026-GN-01187)", customerId="CUS-1001")
    other = await opened(c, subject="Card dispute", customerName="Priya Natarajan", customerId="CUS-1002")

    async def found(text: str) -> list[str]:
        r = await c.get("/v1/cases", params={"search": text, "pageSize": 100}, headers=VIEWER)
        assert r.status_code == 200, r.text
        return [x["id"] for x in r.json()["data"]["data"]]

    assert levy["id"] in await found("marcus") and other["id"] not in await found("marcus")
    by_name = await found("natarajan")
    assert other["id"] in by_name and levy["id"] not in by_name
    assert levy["id"] in await found("CUS-1001") and other["id"] not in await found("CUS-1001")
    assert await found("nothing like this") == []
