"""Mailboxes connected on Channels > Email (c-199), through the routes with tokens minted as platform-service mints
them, by failure mode: a viewer connects one; a builder of another team reads or edits this team's; an address
changes under a live workflow, which then stops receiving mail; the dev folder provider is accepted outside dev; Test
connection sends the password itself, or the wrong team's token, to tools-service; a paused mailbox is still read."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from ops_agents.activities.gateway import GatewayClient
from ops_agents.api.app import create_app
from ops_agents.api.deps import Runtime
from ops_agents.store.base import metadata
from ops_engine.store import metadata as engine_metadata
from ops_identity import (
    Auth,
    Identity,
    ServiceAuth,
    ServiceClient,
    dev_service_signer,
    mint_service_token,
    service_verifiers,
)
from ops_service_kit.settings import Settings
from tests.conftest import SEED, FakeGraphModels, fixture_knowledge, scripted_model
from tests.engine.test_email_trigger_binding import email_workflow
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, VIEWER, introspect, jwks, person

OTHER_TEAM = person("omar", "team_fraud", "builder")
GMAIL: dict[str, Any] = {
    "name": "Levy intake",
    "address": "levy.intake@gmail.com",
    "provider": "gmail",
    "passwordSecret": "GMAIL_APP_PASSWORD",
}


def service(name: str, scopes: list[str], tenant: str = TENANT, team: str = "team_ops") -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service=name, audience="agents", tenant_id=tenant, scopes=scopes, team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


class Stack:
    def __init__(self, c: AsyncClient, rt: Runtime) -> None:
        self.c, self.rt = c, rt

    async def connect(self, body: dict[str, Any] | None = None, who: dict[str, str] = BUILDER) -> httpx.Response:
        return await self.c.post("/v1/channels/mailboxes", json=body or GMAIL, headers=who)


@pytest.fixture
async def stack() -> AsyncIterator[Stack]:
    engine: AsyncEngine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    settings = Settings(database_url="sqlite+aiosqlite://", seed_dir=SEED)
    auth = Auth(
        Identity(
            audience="agents",
            jwks=jwks,
            introspect=introspect,
            key_cache_s=0,
            services=ServiceAuth(
                audience="agents", verifiers=service_verifiers(settings, "agents"), scopes=settings.service_scopes
            ),
        ),
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
        yield Stack(c, app.state.runtime)


async def test_a_builder_connects_a_mailbox_for_the_team_and_a_viewer_cannot(stack: Stack) -> None:
    refused = await stack.connect(who=VIEWER)
    assert refused.status_code == 403, refused.text
    made = await stack.connect()
    assert made.status_code == 201, made.text
    m = made.json()["data"]
    assert (m["teamId"], m["provider"], m["passwordSecret"], m["workflows"]) == (
        "team_ops",
        "gmail",
        "GMAIL_APP_PASSWORD",
        [],
    )
    listed = (await stack.c.get("/v1/channels/mailboxes", headers=VIEWER)).json()["data"]
    assert [x["address"] for x in listed] == ["levy.intake@gmail.com"]
    again = await stack.connect()
    assert again.status_code == 409 and again.json()["error"]["code"] == "address_taken"


async def test_another_teams_builder_neither_sees_nor_edits_it(stack: Stack) -> None:
    mid = (await stack.connect()).json()["data"]["id"]
    assert (await stack.c.get("/v1/channels/mailboxes", headers=OTHER_TEAM)).json()["data"] == []
    for method, path, body in (
        ("GET", f"/v1/channels/mailboxes/{mid}", None),
        ("PATCH", f"/v1/channels/mailboxes/{mid}", {"name": "Theirs"}),
        ("PATCH", f"/v1/channels/{mid}", {"paused": True}),
        ("POST", f"/v1/channels/mailboxes/{mid}/test", None),
    ):
        r = await stack.c.request(method, path, json=body, headers=OTHER_TEAM)
        assert r.status_code == 404, (method, path, r.text)


async def test_an_address_cannot_change_under_a_live_workflow(stack: Stack) -> None:
    mid = (await stack.connect()).json()["data"]["id"]
    saved = await stack.c.post(
        "/v1/workflows/definitions", json={"definition": email_workflow("levy_mail", GMAIL["address"])}, headers=BUILDER
    )
    assert saved.status_code == 201, saved.text
    live = await stack.c.post("/v1/workflows/definitions/levy_mail/publish-requests", json={}, headers=BUILDER)
    assert live.status_code == 201, live.text
    view = (await stack.c.get(f"/v1/channels/mailboxes/{mid}", headers=BUILDER)).json()["data"]
    assert [w["id"] for w in view["workflows"]] == ["levy_mail"]
    moved = await stack.c.patch(f"/v1/channels/mailboxes/{mid}", json={"address": "new@gmail.com"}, headers=BUILDER)
    assert moved.status_code == 409 and moved.json()["error"]["code"] == "mailbox_in_use", moved.text
    renamed = await stack.c.patch(f"/v1/channels/mailboxes/{mid}", json={"name": "Levies"}, headers=BUILDER)
    assert renamed.status_code == 200 and renamed.json()["data"]["name"] == "Levies"
    paused = await stack.c.patch(f"/v1/channels/mailboxes/{mid}", json={"paused": True}, headers=BUILDER)
    assert paused.status_code == 400, "a mailbox is paused as a channel, through PATCH /v1/channels/{id} alone"


async def test_test_connection_sends_the_secrets_name_and_the_mailboxs_team(stack: Stack) -> None:
    sent: list[httpx.Request] = []

    def tools(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        steps = [{"title": "Sign in", "state": "done"}]
        return httpx.Response(200, json={"success": True, "data": {"ok": True, "steps": steps, "newest": None}})

    http = httpx.AsyncClient(base_url="http://tools", transport=httpx.MockTransport(tools))
    stack.rt.tools = GatewayClient(ServiceClient(http, dev_service_signer(), "agents", "tools", tenant=lambda: TENANT))
    r = await stack.c.post("/v1/channels/mailboxes/test", json=GMAIL, headers=BUILDER)
    assert r.status_code == 200 and r.json()["data"]["ok"] is True, r.text
    [req] = sent
    body = json.loads(req.content)
    assert req.url.path == "/v1/mailboxes/test"
    assert body["connection"]["passwordSecret"] == "GMAIL_APP_PASSWORD" and "password" not in body["connection"]
    claims = json.loads(base64.urlsafe_b64decode(req.headers["authorization"].split(".")[1] + "==").decode())
    assert claims["team_id"] == "team_ops" and "deployments:run" in claims["scopes"]
    await http.aclose()


async def test_a_sender_that_could_not_send_is_refused_when_saved(stack: Stack) -> None:
    r = await stack.connect(GMAIL | {"sender": "resend", "fromAddress": "levy.intake@gmail.com"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "sender_incomplete", r.text
    smtp = GMAIL | {"sender": "smtp", "fromAddress": "levy.intake@gmail.com", "senderSecret": "GMAIL_APP_PASSWORD"}
    made = await stack.connect(smtp)
    assert made.status_code == 201 and made.json()["data"]["sender"] == "smtp", made.text
    mid = made.json()["data"]["id"]
    r = await stack.c.patch(f"/v1/channels/mailboxes/{mid}", json={"senderSecret": None}, headers=BUILDER)
    assert r.status_code == 422 and r.json()["error"]["code"] == "sender_incomplete", r.text


async def test_tools_service_reads_its_teams_mailbox_by_address_and_nothing_else(stack: Stack) -> None:
    """tools-service, sending a reply for a run of team_ops, reads that team's mailbox by address: another team's
    token, another tenant's, or one without `deployments:view` reads nothing."""
    await stack.connect(GMAIL | {"sender": "smtp", "fromAddress": GMAIL["address"], "senderSecret": "SMTP_PASSWORD"})
    tools = service("tools", ["deployments:view"])
    r = await stack.c.get("/v1/channels/mailboxes", params={"address": GMAIL["address"].upper()}, headers=tools)
    assert r.status_code == 200, r.text
    [m] = r.json()["data"]
    assert (m["teamId"], m["sender"], m["senderSecret"]) == ("team_ops", "smtp", "SMTP_PASSWORD")
    for h in (
        service("tools", ["deployments:view"], team="team_fraud"),
        service("tools", ["deployments:view"], tenant="other"),
    ):
        r = await stack.c.get("/v1/channels/mailboxes", params={"address": GMAIL["address"]}, headers=h)
        assert r.status_code == 200 and r.json()["data"] == [], r.text
    blind = service("tools", ["workflows:view"])
    r = await stack.c.get("/v1/channels/mailboxes", params={"address": GMAIL["address"]}, headers=blind)
    assert r.status_code == 403, r.text
