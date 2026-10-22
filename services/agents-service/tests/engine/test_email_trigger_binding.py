"""Who may put a workflow on a mailbox (c-187), by failure mode: a person whose roles allow publishing but not
`deployments.create` binds a mailbox; a team's workflow binds a mailbox another team owns; a workflow in another tenant
whose team has the same slug binds it; a workflow no team owns binds one; the mailbox picker offers another team's or
tenant's mailbox. Every call goes through the publish route with a token minted and
verified as platform-service's are."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_access.catalogue import Grant
from ops_access.check import DEFAULT
from ops_agents.api.app import create_app
from ops_agents.store.base import metadata
from ops_agents.store.engine import EngineTransactions
from ops_agents.store.tenancy import tenant_scope
from ops_engine.store import DefinitionStore
from ops_engine.store import metadata as engine_metadata
from ops_identity import Auth, Identity, ServiceAuth, service_verifiers
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_email_trigger import connect
from tests.engine.test_lifecycle_rights import ADMIN, BUILDER, PLATFORM, TENANT, introspect, jwks

MAILBOXES = [
    (TENANT, "levy@bank.example", "team_ops", "imap"),
    (TENANT, "fraud@bank.example", "team_fraud", "dev"),
    # Another tenant's mailbox whose team has the same slug as this tenant's team_ops.
    ("other_tenant", "other@acme-two.example", "team_ops", "dev"),
]
# A custom role that edits and publishes workflows but may not put anything on a channel.
EDITOR_ROLE = "workflow_editor"
EDITOR_GRANTS: tuple[Grant, ...] = tuple(("workflows", a, "all") for a in ("view", "create", "edit", "publish", "run"))
PERM_VERSION = 187


def editor() -> dict[str, str]:
    claims = {
        "sub": "erin",
        "email": "erin@harborpine.example",
        "name": "erin",
        "kind": "person",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops"],
        "access": {"team_ops": [EDITOR_ROLE]},
        "perm_version": PERM_VERSION,
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


def email_workflow(wid: str, mailbox: str) -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "id": wid,
        "name": f"Intake {wid}",
        "nodes": [
            {
                "id": "start",
                "type": "ops.trigger.email",
                "typeVersion": 1,
                "name": "Email received",
                "parameters": {"mailbox": mailbox, "folder": "inbox", "hasAttachment": True},
            },
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ],
        "connections": [{"from": {"node": "start", "port": "payload"}, "to": {"node": "done", "port": "in"}}],
    }


@pytest.fixture
async def stack() -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    for tenant, address, team, provider in MAILBOXES:
        await connect(engine, tenant, address, team=team, provider=provider)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
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
    # The custom role's grid, as platform-service would serve it for this permission version.
    DEFAULT.grids._cache[TENANT] = (PERM_VERSION, {EDITOR_ROLE: EDITOR_GRANTS})  # pyright: ignore[reportPrivateUsage]
    try:
        async with (
            app.router.lifespan_context(app),
            AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c,
        ):
            yield c, engine
    finally:
        DEFAULT.grids._cache.pop(TENANT, None)  # pyright: ignore[reportPrivateUsage]


async def save(c: AsyncClient, d: dict[str, Any], headers: dict[str, str]) -> None:
    r = await c.post("/v1/workflows/definitions", json={"definition": d}, headers=headers)
    assert r.status_code == 201, r.text


async def publish(c: AsyncClient, wid: str, headers: dict[str, str]) -> Any:
    return await c.post(f"/v1/workflows/definitions/{wid}/publish-requests", json={}, headers=headers)


async def test_a_builder_binds_the_teams_own_mailbox(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    await save(c, email_workflow("levy_intake", "Levy@Bank.example"), BUILDER)
    r = await publish(c, "levy_intake", BUILDER)
    assert r.status_code == 201, r.text


async def test_publishing_without_deployments_create_is_refused(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    await save(c, email_workflow("levy_editor", "levy@bank.example"), editor())
    r = await publish(c, "levy_editor", editor())
    assert r.status_code == 403, r.text
    assert "deployments.create" in r.json()["error"]["message"]
    # The same role publishes a workflow that is not on a mailbox: the refusal is the binding's, not the publish's.
    plain: dict[str, Any] = email_workflow("plain_editor", "x") | {
        "nodes": [
            {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "name": "Request", "parameters": {}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "name": "Done", "parameters": {}},
        ]
    }
    await save(c, plain, editor())
    assert (await publish(c, "plain_editor", editor())).status_code == 201


async def test_another_teams_mailbox_is_refused(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    c, _ = stack
    await save(c, email_workflow("fraud_peek", "fraud@bank.example"), BUILDER)
    r = await publish(c, "fraud_peek", BUILDER)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "mailbox_not_offered"


async def test_a_workflow_no_team_owns_cannot_bind_a_mailbox(stack: tuple[AsyncClient, AsyncEngine]) -> None:
    """A workflow no team owns (the seed's) is seen by every team, so binding it would hand one team's mail to all."""
    c, engine = stack
    store = DefinitionStore(EngineTransactions(engine))
    with tenant_scope(TENANT):
        await store.publish(
            "seeded_levy",
            name="Seeded",
            definition=email_workflow("seeded_levy", "levy@bank.example"),
            digest="seeded_levy".ljust(64, "e"),
            now="n",
            by="seed",
        )
    refused = await publish(c, "seeded_levy", ADMIN)
    assert refused.status_code == 422, refused.text
    assert refused.json()["error"]["code"] == "email_trigger_needs_team"


async def test_another_tenants_mailbox_is_refused_whatever_its_team_is_called(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    await save(c, email_workflow("cross_tenant", "other@acme-two.example"), BUILDER)
    r = await publish(c, "cross_tenant", BUILDER)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "mailbox_not_offered"


async def test_the_mailbox_picker_offers_the_acting_teams_mailboxes_only(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, _ = stack
    r = await c.get("/v1/workflows/option-sources", params={"source": "mailboxes"}, headers=BUILDER)
    assert r.status_code == 200, r.text
    assert [(o["value"], o["description"]) for o in r.json()["data"]] == [
        ("levy@bank.example", "levy@bank.example · IMAP")
    ]


async def test_an_email_trigger_naming_no_mailbox_publishes_and_binds_nothing(
    stack: tuple[AsyncClient, AsyncEngine],
) -> None:
    """c-466: with no mailbox set the trigger reads no mail, so publishing authorises nothing; Start run still sends it
    a test email. One naming a mailbox keeps the rule above."""
    c, _ = stack
    for wid, mailbox in (("notices_no_mail", ""), ("notices_unset", None)):
        d = email_workflow(wid, "x")
        params = d["nodes"][0]["parameters"]
        params.pop("mailbox") if mailbox is None else params.update(mailbox=mailbox)
        await save(c, d, editor())
        r = await publish(c, wid, editor())
        assert r.status_code == 201, (wid, r.text)
