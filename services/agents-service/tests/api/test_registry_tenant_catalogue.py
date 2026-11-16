"""The serving catalogue holds every tenant's live agents by id, so a route that takes an agent id from a caller must
find that agent in the caller's tenant first, by failure mode: a caller in another tenant chats with, sets as its
team's default, reads the connectors of, or is offered an agent it cannot see, because the two tenants' teams share an
id."""

from __future__ import annotations

from typing import Any

import pytest

from ops_agents.store.tenancy import tenant_scope
from tests.api.test_registry_tenant_pins import person, published_agent, started, tenants


async def test_another_tenants_agent_id_is_not_found_on_every_chat_route(database_url: str) -> None:
    a, b = tenants()
    async with started(database_url, seed=False) as (client, rt):
        agent = await published_agent(client, rt, a, "Payee desk")
    # Served after a restart, as a published agent is on every instance.
    async with started(database_url, seed=False) as (client, rt):
        theirs = person(b)
        chat = await client.post("/v1/chat/threads", json={"agentId": agent, "kbIds": []}, headers=theirs)
        assert chat.status_code == 404, chat.text
        default = await client.put("/v1/chat/default-agent", json={"agentId": agent}, headers=person(b, role="admin"))
        assert default.status_code == 404, default.text
        connectors = await client.get("/v1/chat/connectors", params={"agentId": agent}, headers=theirs)
        assert connectors.status_code == 404, connectors.text
        offered = await client.get("/v1/chat/agents", headers=theirs)
        assert offered.status_code == 200, offered.text
        assert agent not in [a["id"] for a in offered.json()["data"]], "another tenant's agent is offered to chat with"
        mine = await client.post("/v1/chat/threads", json={"agentId": agent, "kbIds": []}, headers=person(a))
        assert mine.status_code == 201, mine.text


async def test_a_wrapper_run_naming_another_tenants_agent_is_not_found(database_url: str) -> None:
    a, b = tenants()
    async with started(database_url, seed=False) as (client, rt):
        agent = await published_agent(client, rt, a, "Payee desk")
    async with started(database_url, seed=False) as (client, rt):
        theirs = person(b)
        made = await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}}, headers=theirs)
        assert made.status_code == 201, made.text
        tid = made.json()["data"]["threadId"]
        body: dict[str, Any] = {"input": {"agent_id": agent, "message": "What is the payee limit?", "kb_ids": []}}
        run = await client.post(f"/v1/threads/{tid}/runs/stream", json=body, headers=theirs)
        assert run.status_code == 404, run.text
        # The graph refuses too, for a run that reaches it some other way (a recovery, a resume).
        state = {"agent_id": agent, "messages": [{"role": "user", "content": "hi"}]}
        with tenant_scope(b), pytest.raises(ValueError, match="not live"):
            await rt.graphs["agent_wrapper"].ainvoke(state, {"configurable": {"thread_id": tid}})


async def test_two_tenants_teams_of_one_id_each_get_their_own_assistant(database_url: str) -> None:
    a, b = tenants()
    async with started(database_url, seed=False) as (client, rt):
        first = await client.post("/v1/chat/threads", json={"kbIds": []}, headers=person(a))
        assert first.status_code == 201, first.text
        mine = str(first.json()["data"]["agentId"])
        served = rt.catalog.agent(mine)
        second = await client.post("/v1/chat/threads", json={"kbIds": []}, headers=person(b))
        assert second.status_code == 201, second.text
        theirs = str(second.json()["data"]["agentId"])
        assert theirs != mine
        assert rt.catalog.agent(mine) is served, "the other tenant's first chat replaced this tenant's assistant"
        read = await client.get(f"/v1/agents/{theirs}", headers=person(b))
        assert read.status_code == 200, read.text
