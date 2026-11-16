"""The serving catalogue holds every tenant's live agents by id, so a route that takes an agent id from a caller must
find that agent in the caller's tenant first, by failure mode: a caller in another tenant chats with, sets as its
team's default, or reads the connectors of an agent it cannot see, because the two tenants' teams share an id."""

from __future__ import annotations

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
        mine = await client.post("/v1/chat/threads", json={"agentId": agent, "kbIds": []}, headers=person(a))
        assert mine.status_code == 201, mine.text
