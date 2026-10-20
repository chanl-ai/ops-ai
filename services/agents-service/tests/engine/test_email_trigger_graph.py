"""The Email received trigger on a Microsoft 365 mailbox (c-228), by failure mode: a Graph message starts no run, or two
when Graph sends it again; its attachment is not in Files before the run starts. tools-service is faked at its
documented `/v1/mailboxes` API, answering from ops_email's Graph reader over a fake Graph, so the listener's gateway
source, Graph's JSON items and the start path all run as on the stack."""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote

import httpx
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from ops_agents.api.mailbox_gateway import GatewayMailSource
from ops_agents.store.base import metadata
from ops_agents.store.tenancy import current_tenant, tenant_scope
from ops_agents.store.trigger_events import TriggerEvents
from ops_email import GraphMailSource, GraphToken
from ops_engine.store import metadata as engine_metadata
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from tests.engine.test_email_trigger import NOTICE, TEAM, TENANT, Env, FakeFiles, connect
from tests.engine.test_email_trigger_imap import publish_on

MAILBOX = "levy@contoso.example"
DELTA = f"https://graph.test/v1.0/users/{MAILBOX}/mailFolders/inbox/messages/delta"


class FakeGraph:
    """Graph's delta query on one mailbox: `inbox` holds what arrived; a delta link returns what came after it."""

    def __init__(self) -> None:
        self.inbox: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/v2.0/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        assert unquote(request.url.path).startswith(f"/v1.0/users/{MAILBOX}/") and request.headers["authorization"]
        token = request.url.params.get("$deltatoken")
        seen = len(self.inbox) if token == "latest" else int(token or 0)
        return httpx.Response(
            200, json={"value": self.inbox[seen:], "@odata.deltaLink": f"{DELTA}?$deltatoken={len(self.inbox)}"}
        )


class FakeTools:
    """tools-service's /v1/mailboxes for a Microsoft 365 mailbox, answered from ops_email's Graph reader."""

    def __init__(self, graph: FakeGraph) -> None:
        # Cursors tools-service no longer accepts (its key rotated, or one issued before cursors were sealed).
        self.refused: set[str] = set()
        http = httpx.AsyncClient(base_url="https://graph.test", transport=httpx.MockTransport(graph))
        token = GraphToken(http, login_url="https://login.test", tenant="t", client_id="c", secret="s", scope="x")
        self.source = GraphMailSource(http, token, MAILBOX)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body: dict[str, Any] = json.loads(request.content)
        assert body["connection"]["provider"] == "graph" and body["connection"]["graphClientId"] == "app-1"
        if body.get("cursor") in self.refused:
            refusal = {"code": "cursor_refused", "message": "This cursor was not issued for this mailbox."}
            return httpx.Response(422, json={"success": False, "error": refusal})
        if body.get("now"):
            self.refused.clear()  # a cursor issued from now on is sealed with the current key
            data: dict[str, Any] = {"items": [], "nextLink": None, "deltaLink": await self.source.cursor_now()}
        else:
            page = await self.source.delta(body["cursor"])
            data = {"items": page.items, "nextLink": page.next_link, "deltaLink": page.delta_link}
        return httpx.Response(200, json={"success": True, "data": data})


def graph_message(n: int) -> dict[str, Any]:
    """The levy notice as Graph returns it: JSON with the attachment's bytes inline."""
    m = copy.deepcopy(NOTICE)
    return m | {"id": f"AAMk{n}", "internetMessageId": f"<graph-{n}@court.example>"}


@pytest.fixture
async def graph_env(tmp_path: Path) -> AsyncIterator[tuple[Env, FakeGraph]]:
    db = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'agents.db'}")
    async with db.begin() as c:
        await c.run_sync(metadata.create_all)
        await c.run_sync(engine_metadata.create_all)
    await connect(
        db, TENANT, MAILBOX, provider="graph", graph_tenant_id="contoso", graph_client_id="app-1", password_secret="S"
    )
    env = Env(db, tmp_path / "unused", FakeFiles(), Settings())
    graph = FakeGraph()
    tools = FakeTools(graph)
    env.tools = tools  # type: ignore[attr-defined]
    http = httpx.AsyncClient(base_url="http://tools", transport=httpx.MockTransport(tools))
    env.listener = lambda owner="worker:a", sources=None, _l=env.listener: _l(  # type: ignore[method-assign]
        owner,
        lambda m, folder: GatewayMailSource(
            ServiceClient(http, dev_service_signer(), "agents", "tools", ["deployments:run"], tenant=current_tenant),
            m,
            folder,
        ),
    )
    yield env, graph
    await http.aclose()
    await db.dispose()


async def test_a_graph_message_starts_one_run_with_its_attachment_in_files(graph_env: tuple[Env, FakeGraph]) -> None:
    env, graph = graph_env
    await publish_on(env, MAILBOX)
    [first] = await env.listener().poll_all()
    assert first.first_sync and await env.runs() == []
    graph.inbox.append(graph_message(1))
    await env.listener().poll_all()
    [run] = await env.runs()
    [attachment] = run["input"]["attachments"]
    stored = [f for f in env.files.stored.values() if f["purpose"] == "case_attachment"]
    assert [f["id"] for f in stored] == [attachment["fileId"]]
    assert stored[0]["bytes"] == base64.b64decode(NOTICE["attachments"][0]["contentBytes"])
    # Graph sends the same message again under a new id after a delta reset: no second run.
    graph.inbox.append(graph_message(1) | {"id": "AAMk1-again"})
    await env.listener().poll_all()
    assert len(await env.runs()) == 1


def test_an_imap_mailbox_sends_no_graph_fields() -> None:
    # A tools-service from before c-228 refuses unknown connection fields (400), so an IMAP read must not carry them.
    from ops_agents.api.mailbox_gateway import connection  # noqa: PLC0415
    from ops_agents.store.mailboxes import MailboxRow  # noqa: PLC0415

    row = MailboxRow(
        id="mbx_i",
        team_id="t",
        name="n",
        address="a@b.example",
        provider="imap",
        created_by="b",
        created_at="n",
        updated_at="n",
        imap_host="mail.bank.test",
        password_secret="S",
    )
    assert not {"graphTenantId", "graphClientId"} & set(connection(row)), connection(row)


async def test_a_refused_cursor_starts_a_fresh_delta_instead_of_failing_every_poll(
    graph_env: tuple[Env, FakeGraph],
) -> None:
    env, graph = graph_env
    tools = cast(FakeTools, env.tools)  # type: ignore[attr-defined]
    await publish_on(env, MAILBOX)
    await env.listener().poll_all()
    tools.refused.add(f"{DELTA}?$deltatoken=0")  # the cursor the first pass stored
    await env.listener().poll_all()
    graph.inbox.append(graph_message(1))
    await env.listener().poll_all()
    assert len(await env.runs()) == 1, "after the reset, new mail starts its run again"
    # The skipped mail is said, not only logged: one row on the workflow's trigger list, which Activity also lists.
    with tenant_scope(TENANT):
        events, _ = await TriggerEvents(env.db).page("levy_intake", team_id=TEAM, page=1, page_size=10)
    assert [e["outcome"] for e in events] == ["started", "cursor_reset"], events
