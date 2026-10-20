"""Who may write agents, workflows, workflow definitions, guardrails, skills and widgets (c-115), by failure mode: a
viewer's token writes; a reviewer's token writes; a builder acting in another team changes this team's record; a builder
who saved a skill draft deletes a skill another person created. Each walk sends every write the console sends, with
the body it sends, as the refused person first and then as the owning team's builder, whose 2xx proves the body and the
order; tokens are minted and verified as platform-service's are, so the role comes from the token's roles map."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient, Response
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.app import create_app
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from tests.api.test_graph_versions import definition as graph_definition
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_lifecycle import definition
from tests.engine.test_lifecycle_rights import (
    BUILDER,
    PLATFORM,
    TENANT,
    VIEWER,
    jwks,
    person,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    unowned_live,
)

from .test_widget_registry import LIMIT_CARD

REVIEWER = person("maya", "team_ops", "approver")
# A builder, acting in the team the token names: another team's records are not theirs to change.
OTHER_TEAM = person("omar", "team_fraud", "builder")
SECOND_BUILDER = person("jane", "team_ops", "builder")
# The token platform-service mints: auth_method dev on every session, which makes agents-service read across teams.
# The role rule must hold on it as on a session token.
VIEWER_DEV_SIGN_IN = {
    **VIEWER,
    "Authorization": "Bearer "
    + mint(
        {
            "sub": "vera",
            "email": "vera@northfield.example",
            "name": "vera",
            "kind": "person",
            "aud": ["agents"],
            "tenant_id": TENANT,
            "team_ids": ["team_ops"],
            "roles": {"team_ops": "viewer"},
            "auth_method": "dev",
        },
        PLATFORM,
        ttl_s=TEST_TOKEN_TTL_S,
    ),
}
# A v1 graph definition (the seeded dispute_email); POST /v1/graphs/{name}/versions names it after the path.
GRAPH = graph_definition(1)

EMAIL: dict[str, Any] = {
    "sender": "ana@example.com",
    "subject": "Payee",
    "body": "Is the payee fine?",
    "attachments": [],
}
RULE: dict[str, Any] = {"name": "No tax advice", "topics": ["tax advice"], "message": "I can't give tax advice."}
SKILL: dict[str, Any] = {
    "name": "Address change",
    "useWhen": "The customer asks to change their postal address.",
    "instructions": "Confirm the customer, then record the new address.",
    "ownerTeam": "Retail",
}

# One write: its method, what it does, its path and body from what the walk has made so far, the status the owning
# builder gets, and what a builder of another team gets: 403 `team_forbidden` naming team_ops (T), 404 for a v2
# definition, which is read inside the acting team already, as c-064 will make every record (N), or nothing sent for a
# create, which acts in the caller's own team (-).
Step = tuple[str, str, Callable[[dict[str, Any]], tuple[str, Any]], int, str]
T, N, OWN = "team_forbidden", "not_found", "-"
# Deleting a shared skill or guardrail keeps its creator-or-admin rule (agent_registry.require_owner_or_admin), with
# its own message and code.
OWNER_RULE = {"delete a skill", "delete a guardrail"}
# What is wrong with the refused person's answer to one step, or None when it was refused as it should be.
Expect = Callable[[Step, Response], str | None]


async def _no_keys(_key: str) -> dict[str, Any] | None:
    return None


@asynccontextmanager
async def reviewed_stack(engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    """The same database served with the dev auto-approve setting off, as every deployed environment runs."""
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED, registry_auto_approve=False)
    auth = Auth(
        Identity(audience="agents", jwks=jwks, introspect=_no_keys, key_cache_s=0),
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
        yield c


def _data(r: Response) -> Any:
    return r.json()["data"]


STEPS: list[Step] = [
    ("POST", "create a skill", lambda k: ("/v1/skills", SKILL), 201, OWN),
    (
        "PUT",
        "save a skill draft",
        lambda k: (f"/v1/skills/{k['skill']}/draft", {"note": "x", "baseVersion": 1}),
        200,
        T,
    ),
    ("POST", "ask to publish a skill", lambda k: (f"/v1/skills/{k['skill']}/publish-requests", {"note": "go"}), 201, T),
    ("POST", "create an agent", lambda k: ("/v1/agents", {"name": "Payee checker", "role": "Checks payees"}), 201, OWN),
    ("PATCH", "edit an agent", lambda k: (f"/v1/agents/{k['agent']}", {"role": "Checks new payees"}), 200, T),
    ("POST", "test an agent", lambda k: (f"/v1/agents/{k['agent']}/test", {"message": "hello"}), 200, T),
    ("POST", "restore an agent version", lambda k: (f"/v1/agents/{k['agent']}/versions/1/restore", None), 200, T),
    ("PUT", "pin a skill", lambda k: (f"/v1/agents/{k['agent']}/skills/{k['skill']}", {"version": 1}), 200, T),
    ("DELETE", "unpin a skill", lambda k: (f"/v1/agents/{k['agent']}/skills/{k['skill']}", None), 200, T),
    (
        "POST",
        "ask to publish an agent",
        # The edits above rewrite the one draft (c-172), so it is still v1.
        lambda k: (f"/v1/agents/{k['agent']}/publish-requests", {"version": 1}),
        201,
        T,
    ),
    ("POST", "pause an agent", lambda k: (f"/v1/agents/{k['agent']}/paused", {"paused": True}), 200, T),
    ("POST", "deprecate a skill", lambda k: (f"/v1/skills/{k['skill']}/deprecate", {"reason": "Replaced"}), 200, T),
    ("DELETE", "delete a skill", lambda k: (f"/v1/skills/{k['skill']}", None), 204, T),
    ("DELETE", "delete an agent", lambda k: (f"/v1/agents/{k['agent']}", None), 204, T),
    ("POST", "create a guardrail", lambda k: ("/v1/guardrails", RULE), 201, OWN),
    ("PATCH", "edit a guardrail", lambda k: (f"/v1/guardrails/{k['guardrail']}", {"topics": ["tax"]}), 200, T),
    (
        "POST",
        "ask to publish a guardrail",
        lambda k: (f"/v1/guardrails/{k['guardrail']}/publish-requests", {"version": 2}),
        201,
        T,
    ),
    (
        "POST",
        "deprecate a guardrail",
        lambda k: (f"/v1/guardrails/{k['guardrail']}/status", {"status": "deprecated"}),
        200,
        T,
    ),
    ("DELETE", "delete a guardrail", lambda k: (f"/v1/guardrails/{k['guardrail']}", None), 204, T),
    (
        "POST",
        "create a workflow",
        lambda k: ("/v1/workflows", {"name": "Payee check", "template": "approval"}),
        201,
        OWN,
    ),
    (
        "PATCH",
        "edit a workflow",
        lambda k: (f"/v1/workflows/{k['workflow']}", {"description": "Checks payees"}),
        200,
        T,
    ),
    ("PUT", "save a workflow draft", lambda k: (f"/v1/workflows/{k['workflow']}/draft", {"graph": k["graph"]}), 200, T),
    (
        "POST",
        "validate a workflow",
        lambda k: (f"/v1/workflows/{k['workflow']}/validate", {"graph": k["graph"]}),
        200,
        T,
    ),
    ("POST", "test a workflow", lambda k: (f"/v1/workflows/{k['workflow']}/test", {"email": EMAIL}), 200, T),
    (
        "POST",
        "publish a workflow",
        lambda k: (f"/v1/workflows/{k['workflow']}/publish-requests", {"graph": k["graph"]}),
        201,
        T,
    ),
    (
        "POST",
        "publish a graph version of a workflow",
        lambda k: (f"/v1/graphs/{k['workflow']}/versions", {"definition": GRAPH}),
        201,
        T,
    ),
    ("POST", "pause a workflow", lambda k: (f"/v1/workflows/{k['workflow']}/status", {"status": "paused"}), 200, T),
    ("POST", "roll a workflow back", lambda k: (f"/v1/workflows/{k['workflow']}/pointer", {"version": 1}), 200, T),
    (
        "POST",
        "restore a workflow version",
        lambda k: (f"/v1/workflows/{k['workflow']}/versions/1/restore", None),
        200,
        T,
    ),
    ("DELETE", "discard a workflow draft", lambda k: (f"/v1/workflows/{k['workflow']}/draft", None), 200, T),
    ("DELETE", "delete a workflow", lambda k: (f"/v1/workflows/{k['workflow']}", None), 204, T),
    (
        "POST",
        "save a workflow definition",
        lambda k: ("/v1/workflows/definitions", {"definition": definition("c115_refunds")}),
        201,
        OWN,
    ),
    (
        "POST",
        "ask to publish a definition",
        lambda k: ("/v1/workflows/definitions/c115_refunds/publish-requests", {}),
        201,
        N,
    ),
    ("POST", "pause a definition", lambda k: ("/v1/workflows/definitions/c115_refunds/pause", None), 200, N),
    ("POST", "resume a definition", lambda k: ("/v1/workflows/definitions/c115_refunds/resume", None), 200, N),
    ("DELETE", "delete a definition", lambda k: ("/v1/workflows/definitions/c115_refunds", None), 204, N),
    (
        "POST",
        "save a second definition",
        lambda k: ("/v1/workflows/definitions", {"definition": definition("c115_tested")}),
        201,
        OWN,
    ),
    (
        "POST",
        "start a test run of a definition",
        lambda k: ("/v1/runs", {"workflowId": "c115_tested", "mode": "test", "input": {"amount": 5}}),
        202,
        N,
    ),
    ("POST", "create a widget", lambda k: ("/v1/widgets", LIMIT_CARD), 201, OWN),
]


async def _send(c: AsyncClient, method: str, path: str, body: Any, headers: dict[str, str]) -> Response:
    return await c.request(method, path, json=body, headers=headers)


async def _remember(c: AsyncClient, what: str, made: Response, kept: dict[str, Any]) -> None:
    """Keeps the ids and the draft graph the later steps write to."""
    if what == "create a skill":
        kept["skill"] = _data(made)["id"]
    elif what == "create an agent":
        kept["agent"] = _data(made)["id"]
    elif what == "create a guardrail":
        kept["guardrail"] = _data(made)["id"]
    elif what == "create a workflow":
        kept["workflow"] = _data(made)["id"]
        detail = _data(await c.get(f"/v1/workflows/{kept['workflow']}", headers=BUILDER))
        kept["graph"] = detail["draft"]["graph"]


async def _walk(c: AsyncClient, refused: dict[str, str], expect: Expect, *, creates: bool) -> list[str]:
    """Each step as the refused person, then as the owning builder, collecting every write the refused person was not
    refused as it should be. A refused write that went through stands in for the builder's, so the walk goes on and
    names every route at once. With `creates` false the creates are sent only by the builder."""
    kept: dict[str, Any] = {}
    problems: list[str] = []
    for step in STEPS:
        method, what, target, status, other = step
        path, body = target(kept)
        made: Response | None = None
        if creates or other != OWN:
            r = await _send(c, method, path, body, refused)
            if (problem := expect(step, r)) is not None:
                problems.append(f"{what} ({method} {path}): {problem}")
            if r.is_success:
                made = r
        if made is None:
            made = await _send(c, method, path, body, BUILDER)
            if made.status_code != status:
                problems.append(f"{what} as the owning builder: {made.status_code} {made.text[:300]}")
                break
        await _remember(c, what, made, kept)
    return problems


@pytest.mark.parametrize(
    "refused", [VIEWER, REVIEWER, VIEWER_DEV_SIGN_IN], ids=["viewer", "reviewer", "viewer-dev-sign-in"]
)
async def test_a_viewer_or_reviewer_is_refused_every_write(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
    refused: dict[str, str],
) -> None:
    c, _ = stack

    def expect(step: Step, r: Response) -> str | None:
        if r.status_code != 403:
            return f"{r.status_code} {r.text[:120]}"
        code = r.json()["error"]["code"]
        return None if step[1] in OWNER_RULE or code == "role_required" else f"403 {code}"

    problems = await _walk(c, refused, expect, creates=True)
    assert not problems, "\n".join(problems)


async def test_a_builder_of_another_team_cannot_change_this_teams_records(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack

    def expect(step: Step, r: Response) -> str | None:
        what, other = step[1], step[4]
        if other == N:
            return None if r.status_code == 404 else f"{r.status_code} {r.text[:120]}"
        if r.status_code != 403:
            return f"{r.status_code} {r.text[:120]}"
        error: dict[str, Any] = r.json()["error"]
        details: dict[str, Any] = error.get("details") or {}
        named = error["code"] == "team_forbidden" and details.get("teamId") == "team_ops"
        return None if what in OWNER_RULE or named else f"403 {error}"

    problems = await _walk(c, OTHER_TEAM, expect, creates=False)
    assert not problems, "\n".join(problems)


async def test_a_skill_is_deleted_by_its_creator_not_its_last_saver(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    made = await c.post("/v1/skills", json=SKILL, headers=BUILDER)
    assert made.status_code == 201, made.text
    sid = _data(made)["id"]
    # Another builder of the team saves the unpublished draft, which rewrites version 1's saver.
    saved = await c.put(f"/v1/skills/{sid}/draft", json={"note": "x", "baseVersion": 1}, headers=SECOND_BUILDER)
    assert saved.status_code == 200, saved.text
    refused = await c.delete(f"/v1/skills/{sid}", headers=SECOND_BUILDER)
    assert refused.status_code == 403, refused.text
    assert (await c.delete(f"/v1/skills/{sid}", headers=BUILDER)).status_code == 204


async def test_a_graph_version_needs_a_builder_and_a_workflow_needs_its_review(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """POST /v1/graphs/{name}/versions publishes with no review and points new threads at the version. A graph the
    registry does not hold takes a builder of the acting team; a registry workflow takes a builder of its team and,
    outside the dev auto-approve setting, its review (409 review_required)."""
    c, engine = stack
    path = "/v1/graphs/c115_free_graph/versions"
    for who in (VIEWER, REVIEWER):
        r = await c.post(path, json={"definition": GRAPH}, headers=who)
        assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text
    assert (await c.post(path, json={"definition": GRAPH}, headers=BUILDER)).status_code == 201

    made = await c.post("/v1/workflows", json={"name": "Reviewed", "template": "approval"}, headers=BUILDER)
    assert made.status_code == 201, made.text
    wid = _data(made)["id"]
    async with reviewed_stack(engine) as reviewed:
        r = await reviewed.post(f"/v1/graphs/{wid}/versions", json={"definition": GRAPH}, headers=BUILDER)
        assert r.status_code == 409 and r.json()["error"]["code"] == "review_required", r.text


async def test_channel_writes_need_a_builder_of_the_owning_team(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """A deployment puts a graph on a channel; a delivered channel message resumes a thread.
    Each is a builder's step in the team that owns the deployment or thread; a builder of another team is refused with
    that team named, on a change to the record as on a create under its id."""
    c, _ = stack
    dep = {"id": "dep_c115", "graph": "complex_workflow", "channel": "api"}
    made = await c.post("/v1/deployments", json=dep, headers=BUILDER)
    assert made.status_code == 201, made.text
    thread = await c.post("/v1/threads", json={"graph": "dispute_email"}, headers=BUILDER)
    assert thread.status_code == 201, thread.text
    tid = _data(thread)["threadId"]
    writes: list[tuple[str, str, dict[str, Any] | None]] = [
        ("POST", "/v1/deployments", {**dep, "paused": True}),
        ("PATCH", "/v1/deployments/dep_c115", {"paused": True}),
        ("POST", f"/v1/threads/{tid}/inbox", {"kind": "customer_reply", "messageKey": "m1", "payload": {}}),
    ]
    problems: list[str] = []
    for who, code in ((VIEWER, "role_required"), (REVIEWER, "role_required"), (OTHER_TEAM, "team_forbidden")):
        for method, path, body in writes:
            if who is OTHER_TEAM and path.endswith("/inbox"):
                continue  # a thread of another team is refused by its team check before any role (R6)
            r = await c.request(method, path, json=body, headers=who)
            got = r.json()["error"]["code"] if r.status_code == 403 else None
            if r.status_code != 403 or got != code:
                problems.append(f"{method} {path} as {code}: {r.status_code} {r.text[:120]}")
    assert not problems, "\n".join(problems)
    # The control: the owning builder's change and pause go through; the inbox passes the role check and fails later
    # on this stack (a thread waiting on nothing).
    assert (await c.post("/v1/deployments", json=dep, headers=BUILDER)).status_code == 201
    assert (await c.patch("/v1/deployments/dep_c115", json={"paused": True}, headers=BUILDER)).status_code == 200
    for method, path, body in writes[2:]:
        r = await c.request(method, path, json=body, headers=BUILDER)
        assert r.status_code not in (401, 403), f"{path}: {r.text}"


async def test_the_saver_of_a_workflow_no_team_owns_needs_a_builder_role(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """A creator who has since become a viewer reads only, as an API key carrying its creator's email does."""
    c, engine = stack
    await unowned_live(engine, "james_refunds", by="james@northfield.example")
    demoted = person("james", "team_ops", "viewer")
    r = await c.post("/v1/workflows/definitions/james_refunds/pause", headers=demoted)
    assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", r.text
    assert (await c.post("/v1/workflows/definitions/james_refunds/pause", headers=BUILDER)).status_code == 200


async def test_thread_control_writes_need_a_builder(stack: tuple[AsyncClient, AsyncEngine]) -> None:  # noqa: F811
    """Moving a waiting thread to another version and posting a channel event to it change how a run continues."""
    c, _ = stack
    made = await c.post("/v1/threads", json={"graph": "dispute_email"}, headers=BUILDER)
    assert made.status_code == 201, made.text
    tid = _data(made)["threadId"]
    writes: list[tuple[str, dict[str, Any]]] = [
        (f"/v1/threads/{tid}/migrate", {"toVersion": 1}),
        (f"/v1/threads/{tid}/events", {"type": "customer_reply"}),
    ]
    for who in (VIEWER, REVIEWER):
        for path, body in writes:
            r = await c.post(path, json=body, headers=who)
            assert r.status_code == 403 and r.json()["error"]["code"] == "role_required", f"{path}: {r.text}"
    # The control: a builder passes the role check and meets the thread's own state (it waits on nothing yet).
    for path, body in writes:
        r = await c.post(path, json=body, headers=BUILDER)
        assert r.status_code == 409, f"{path}: {r.text}"
