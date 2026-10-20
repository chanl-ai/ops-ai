"""Who may start and cancel runs, decide reviews and chat (c-122), by failure mode: a viewer or reviewer starts a run,
or a key starts a test run; someone cancels another person's run without being an admin or reviewer, or a key cancels
a run it did not start; a builder or a key decides a review, a publish or a paused step, or a reviewer decides another
team's; a person acting in another team chats with this team's agent. Tokens are minted and verified as
platform-service's are, so each role comes from the token's roles map; the API key is introspected as platform-service
answers for a write key of team_ops."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model, sse_events
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, VIEWER, jwks, person, unowned_live

REVIEWER = person("maya", "team_ops", "approver")
SECOND_BUILDER = person("jane", "team_ops", "builder")
OTHER_REVIEWER = person("nadia", "team_fraud", "approver")
OUTSIDER = person("omar", "team_fraud", "builder")
KEY = {"X-API-Key": "ok_ops.k1", "X-Team-Id": "team_ops"}
EMAILS: list[dict[str, Any]] = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "seed" / "dispute_emails.json").read_text()
)


# Keys scoped to one agent or workflow (c-246), as platform-service introspects them; ok_ops.k1 has no target and
# answers as platform-service did before keys carried one.
TARGETS: dict[str, dict[str, Any]] = {
    "ok_ops.wf": {"kind": "workflow", "id": "refunds", "version": None},
    "ok_ops.pin": {"kind": "workflow", "id": "refunds", "version": 1},
    "ok_ops.agent": {"kind": "agent", "id": "ag_branch", "version": None},
}


async def introspect(key: str) -> dict[str, Any] | None:
    if key != "ok_ops.k1" and key not in TARGETS:
        return None
    found: dict[str, Any] = {
        "sub": "key_ops",
        "email": "case-system@northfield.example",
        "name": "case system",
        "tenantId": "acme",
        "teamId": "team_ops",
        "scopes": ["read", "write"],
    }
    if key in TARGETS:
        found["apiKey"] = {"id": "key_" + key.split(".")[1], "target": TARGETS[key]}
    return found


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    # Publish requests wait for a reviewer, as every deployed environment runs.
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, registry_auto_approve=False)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=introspect, key_cache_s=0),
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
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
    ):
        yield c, engine


def refused(res: Response, code: str = "role_required") -> bool:
    return res.status_code == 403 and res.json()["error"]["code"] == code


def live_run(n: int) -> dict[str, Any]:
    return {"workflowId": "refunds", "mode": "live", "input": {"amount": 5}, "runKey": f"k{n}"}


async def test_a_live_run_needs_a_builder_admin_or_a_team_key(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    viewer = await c.post("/v1/runs", json=live_run(1), headers=VIEWER)
    reviewer = await c.post("/v1/runs", json=live_run(2), headers=REVIEWER)
    key = await c.post("/v1/runs", json=live_run(3), headers=KEY)
    builder = await c.post("/v1/runs", json=live_run(4), headers=BUILDER)
    assert refused(viewer) and refused(reviewer), (viewer.text, reviewer.text)
    assert key.status_code == 202 and builder.status_code == 202, (key.text, builder.text)


async def test_a_key_never_starts_a_test_run(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    res = await c.post("/v1/runs", json={**live_run(1), "mode": "test"}, headers=KEY)
    assert refused(res), res.text


async def test_a_run_is_cancelled_by_its_starter_or_an_admin_or_reviewer(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    ids = [(await c.post("/v1/runs", json=live_run(n), headers=BUILDER)).json()["data"]["runId"] for n in range(3)]
    cancel = [f"/v1/runs/{i}/cancel" for i in ids]
    others = [await c.post(cancel[0], headers=h) for h in (SECOND_BUILDER, VIEWER, KEY)]
    assert all(refused(r) for r in others), [r.text for r in others]
    allowed = [await c.post(cancel[0], headers=BUILDER), await c.post(cancel[1], headers=REVIEWER)]
    allowed.append(await c.post(cancel[2], headers=ADMIN))
    assert [r.status_code for r in allowed] == [200, 200, 200], [r.text for r in allowed]


async def test_a_key_cancels_only_its_own_run(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, engine = stack
    await unowned_live(engine, "refunds", by="seed")
    run_id = (await c.post("/v1/runs", json=live_run(1), headers=KEY)).json()["data"]["runId"]
    assert (await c.post(f"/v1/runs/{run_id}/cancel", headers=KEY)).status_code == 200


async def test_a_v1_thread_and_its_run_need_the_run_start_rule(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    body: dict[str, Any] = {"graph": "complex_workflow", "metadata": {}}
    viewer = await c.post("/v1/threads", json=body, headers=VIEWER)
    key = await c.post("/v1/threads", json=body, headers=KEY)
    tid = (await c.post("/v1/threads", json=body, headers=BUILDER)).json()["data"]["threadId"]
    run = await c.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAILS[1]}}, headers=REVIEWER)
    assert refused(viewer) and key.status_code == 201 and refused(run), (viewer.text, key.text, run.text)


async def paused_case(c: AsyncClient, budget: dict[str, Any] | None = None) -> str:
    body: dict[str, Any] = {"graph": "complex_workflow", "metadata": {}, **({"budget": budget} if budget else {})}
    tid = (await c.post("/v1/threads", json=body, headers=BUILDER)).json()["data"]["threadId"]
    res = await c.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAILS[1]}}, headers=BUILDER)
    assert sse_events(res.text)[-1]["data"]["status"] == "interrupted", res.text
    return tid


async def test_routing_to_people_and_the_manual_step_need_a_reviewer(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    tid = (await c.post("/v1/threads", json={"graph": "dispute_email", "metadata": {}}, headers=BUILDER)).json()["data"]
    tid = tid["threadId"]
    run = await c.post(f"/v1/threads/{tid}/runs/stream", json={"input": {"email": EMAILS[1]}}, headers=BUILDER)
    assert sse_events(run.text)[-1]["data"]["status"] == "interrupted", run.text
    route = f"/v1/threads/{tid}/route-to-people"
    builder_routes = await c.post(route, json={"reason": "bad version"}, headers=SECOND_BUILDER)
    routed = await c.post(route, json={"reason": "bad version"}, headers=REVIEWER)
    assert refused(builder_routes) and routed.status_code == 202, (builder_routes.text, routed.text)
    url = f"/v1/threads/{tid}/runs/stream"
    answers = [await c.post(url, json={"resume": {"decision": "rejected"}}, headers=h) for h in (SECOND_BUILDER, KEY)]
    assert all(refused(r) for r in answers), [r.text for r in answers]
    assert (await c.post(url, json={"resume": {"decision": "rejected"}}, headers=REVIEWER)).status_code == 200


async def test_a_review_is_decided_by_a_reviewer_of_its_team(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    tid = await paused_case(c)
    url = f"/reviews/{tid}/decision"
    body = {"decision": "rejected", "reason": "not this one"}
    wrong = [await c.post(url, json=body, headers=h) for h in (SECOND_BUILDER, KEY, OTHER_REVIEWER)]
    assert all(r.status_code == 403 for r in wrong), [r.text for r in wrong]
    assert refused(wrong[0]) and refused(wrong[1])
    assert (await c.post(url, json=body, headers=REVIEWER)).status_code == 200


async def test_a_publish_is_decided_by_a_reviewer_of_the_owning_team(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    made = (await c.post("/v1/agents", json={"name": "Branch Desk", "role": "Answers"}, headers=BUILDER)).json()["data"]
    req = await c.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": made["version"], "note": "go"}, headers=BUILDER
    )
    assert req.status_code == 201, req.text
    url = f"/v1/publish-requests/{req.json()['data']['id']}/decision"
    wrong = [await c.post(url, json={"decision": "approved"}, headers=h) for h in (SECOND_BUILDER, KEY, OTHER_REVIEWER)]
    assert all(refused(r) for r in wrong), [r.text for r in wrong]
    assert (await c.post(url, json={"decision": "approved"}, headers=REVIEWER)).status_code == 200


async def test_chat_is_open_to_every_role_of_the_agents_team_and_no_other(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    body: dict[str, Any] = {"agentId": "ag_fraud", "kbIds": []}
    viewer = await c.post("/chat/threads", json=body, headers=VIEWER)
    outsider = await c.post("/chat/threads", json=body, headers=OUTSIDER)
    assert viewer.status_code == 201 and refused(outsider, "team_forbidden"), (viewer.text, outsider.text)


WRITE = 'call request_document {"customerId": "C-1042", "document": "proof of address", "reason": "Moved"}'


async def test_a_write_in_chat_is_approved_by_a_reviewer_of_the_threads_team(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    made = await c.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=BUILDER)
    tid = made.json()["data"]["id"]
    sent = await c.post(
        f"/chat/threads/{tid}/messages", json={"content": WRITE}, headers={**BUILDER, "Accept": "text/event-stream"}
    )
    events = sse_events(sent.text)
    widget = next(e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval")
    action = f"/chat/threads/{tid}/messages/{events[0]['messageId']}/widgets/{widget['id']}/actions"
    in_chat = await c.post(action, json={"type": "approve"}, headers=SECOND_BUILDER)
    direct = await c.post(f"/v1/threads/{tid}/approvals", json={}, headers=SECOND_BUILDER)
    assert in_chat.status_code == 403 and refused(direct), (in_chat.text, direct.text)
    assert (await c.post(action, json={"type": "approve"}, headers=REVIEWER)).status_code == 200


async def test_a_guardrail_publish_is_decided_by_a_reviewer_of_its_team(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    rule = {"name": "No tax advice", "topics": ["tax advice"], "message": "I can't give tax advice."}
    g = (await c.post("/v1/guardrails", json=rule, headers=BUILDER)).json()["data"]
    asked = await c.post(f"/v1/guardrails/{g['id']}/publish-requests", json={"version": 1}, headers=BUILDER)
    request_id = asked.json()["data"]["pendingRequestId"]
    assert request_id, asked.text
    url = f"/v1/guardrails/{g['id']}/publish-requests/{request_id}/decision"
    wrong = [await c.post(url, json={"decision": "approved"}, headers=h) for h in (SECOND_BUILDER, KEY)]
    assert all(refused(r) for r in wrong), [r.text for r in wrong]
    assert (await c.post(url, json={"decision": "approved"}, headers=REVIEWER)).status_code == 200
