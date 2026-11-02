"""An agent's newly granted tool is offered in chat right after its publish is approved (c-616 S7), by failure mode:
a publish request still waiting on an older version refused the request for the newest draft, so the only approval on
offer put the older version live; and the turn's grants came from a tools list kept for 30 s, read before the tool was
published, so the granted tool was dropped from the turn without a word."""

from __future__ import annotations

from pathlib import Path

import httpx

from ops_agents.activities.tool_directory import ToolsOperations, grants_for
from ops_agents.store.tenancy import current_tenant, tenant_scope
from ops_identity import ServiceClient, dev_service_signer

from ..unit.test_tool_directory import Clock, Tools, op
from .test_agent_limits import _app, _data  # pyright: ignore[reportPrivateUsage]
from .test_chat import send

LEE = {"X-Dev-User": "lee@harborpine.example"}
KIM = {"X-Dev-User": "kim@harborpine.example"}


async def publish(c: httpx.AsyncClient, agent_id: str, version: int) -> None:
    asked = _data(await c.post(f"/v1/agents/{agent_id}/publish-requests", json={"version": version}, headers=LEE), 201)
    decided = await c.post(f"/v1/publish-requests/{asked['id']}/decision", json={"decision": "approved"}, headers=KIM)
    assert decided.status_code == 200, decided.text


async def turn(c: httpx.AsyncClient, agent_id: str, text: str) -> str:
    thread = _data(await c.post("/chat/threads", json={"agentId": agent_id, "kbIds": []}), 201)
    raw, _ = await send(c, thread["id"], {"content": text})
    return raw


async def test_a_grant_saved_while_an_older_publish_waits_is_what_goes_live(tmp_path: Path) -> None:
    """A publish request opened earlier (a seed change, a colleague's) waits for version N; the builder grants a tool,
    saves N+1 and asks to publish it. Approving must put N+1 live, or chat runs N without the tool."""
    tools = Tools({"local": [op("lookup_account"), op("list_cases"), op("read_file")]})
    async with _app(tmp_path, registry_auto_approve=False, dev_policies={"requesterMayDecide": False}) as (c, app):
        client = httpx.AsyncClient(transport=httpx.MockTransport(tools.handler), base_url="http://tools")
        service = ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=current_tenant)
        app.state.runtime.tool_directory = ToolsOperations(service, ttl_s=30, clock=Clock())
        agent = _data(await c.post("/v1/agents", json={"name": "Desk helper", "role": "Helps"}, headers=LEE), 201)
        saved = _data(await c.patch(f"/v1/agents/{agent['id']}", json={"toolIds": ["lookup_account"]}, headers=LEE))
        await publish(c, agent["id"], saved["version"])
        cases = ["lookup_account", "list_cases"]
        renamed = _data(await c.patch(f"/v1/agents/{agent['id']}", json={"toolIds": cases}, headers=LEE))
        waiting = _data(
            await c.post(
                f"/v1/agents/{agent['id']}/publish-requests", json={"version": renamed["version"]}, headers=LEE
            ),
            201,
        )
        granted = _data(
            await c.patch(f"/v1/agents/{agent['id']}", json={"toolIds": [*cases, "read_file"]}, headers=LEE)
        )
        assert waiting["status"] == "pending", waiting
        asked = await c.post(
            f"/v1/agents/{agent['id']}/publish-requests", json={"version": granted["version"]}, headers=LEE
        )
        assert asked.status_code == 201, asked.text
        old = _data(await c.get(f"/v1/publish-requests/{waiting['id']}", headers=KIM))
        assert old["status"] == "returned", old
        late = await c.post(
            f"/v1/publish-requests/{waiting['id']}/decision", json={"decision": "approved"}, headers=KIM
        )
        assert late.status_code == 409 and late.json()["error"]["code"] == "already_decided", late.text
        decided = await c.post(
            f"/v1/publish-requests/{asked.json()['data']['id']}/decision", json={"decision": "approved"}, headers=KIM
        )
        assert decided.status_code == 200, decided.text
        after = await turn(c, agent["id"], 'call read_file {"id": "notice.pdf"}')
        assert "read_file" in after, after[:2000]


async def test_a_tool_published_after_the_list_was_kept_is_handed_to_the_turn() -> None:
    """The 30 s list was read before a module was published (an editor's list, an earlier turn), then the agent was
    granted its tool and published: the turn's grants must hold it, not wait for the list to expire (uc-048)."""
    tools, clock = Tools({"local": [op("lookup_account")]}), Clock()
    client = httpx.AsyncClient(transport=httpx.MockTransport(tools.handler), base_url="http://tools")
    service = ServiceClient(client, dev_service_signer(), "agents", "tools", tenant=current_tenant)
    directory = ToolsOperations(service, ttl_s=30, clock=clock)
    with tenant_scope("local"):
        assert [g.name for g in await grants_for(directory, ["lookup_account", "read_file"])] == ["lookup_account"]
        tools.by_tenant["local"].append(op("read_file"))
        assert [g.name for g in await grants_for(directory, ["lookup_account", "read_file"])] == [
            "lookup_account",
            "read_file",
        ]
        # A name tools-service no longer offers costs one read per turn, never a loop.
        before = len(tools.requests)
        await grants_for(directory, ["lookup_account", "gone_tool"])
        assert len(tools.requests) - before <= 1
