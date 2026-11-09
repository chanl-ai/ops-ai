"""A chat's connectors (the composer's picker), by failure mode: turning a connector off still offers its tools to the
model; a chat can turn on an app the agent was not granted, or one the team has off; the choice leaks into the next
chat; and choosing connectors wipes a tool the person switched off one by one in the settings panel."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from httpx import AsyncClient

from ops_agents.activities.tool_directory import CatalogTools, OperationRef
from ops_agents.api.deps import Runtime
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
from tests.api.test_chat_settings import LOOKUP, calls, settings

MODULES = {"lookup_account": "mod_crm", "place_wire_hold": "mod_wires"}
CRM, WIRES, CORE = "plugin:test.crm", "plugin:test.wires", "plugin:test.core"


class Modules:
    """The catalog's tools, each in the module of an app."""

    def __init__(self, rt: Runtime) -> None:
        self.inner = CatalogTools(rt.catalog)

    async def operations(self) -> list[OperationRef]:
        return [replace(o, module_id=MODULES.get(o.name, o.module_id)) for o in await self.inner.operations()]


class Cards:
    """The team's apps for the person: the CRM connected, Wires waiting for their own sign-in, Core banking off."""

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        return [
            {"id": CRM, "kind": "plugin", "name": "CRM", "appState": "connected", "moduleIds": ["mod_crm"]},
            {
                "id": WIRES, "kind": "plugin", "name": "Wires", "appState": "needs_sign_in", "signIn": "person",
                "moduleIds": ["mod_wires"],
            },
            {
                "id": CORE, "kind": "plugin", "name": "Core banking", "appState": "off",
                "moduleIds": ["mod_core"],
            },
        ]  # fmt: skip


def wire(rt: Runtime) -> None:
    rt.tool_directory, rt.app_states = Modules(rt), Cards()


async def connectors(client: AsyncClient, tid: str) -> dict[str, dict[str, Any]]:
    got = await client.get(f"/chat/threads/{tid}/connectors")
    assert got.status_code == 200, got.text
    return {c["appId"]: c for c in got.json()["data"]["connectors"]}


async def test_a_connector_turned_off_is_not_offered_in_that_chat_and_the_next_chat_has_it(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    start = await connectors(client, tid)
    assert {k: (v["appState"], v["on"]) for k, v in start.items()} == {
        CRM: ("connected", True),
        WIRES: ("needs_sign_in", True),
        CORE: ("off", False),
    }, start
    assert start[CRM]["tools"] == ["lookup_account"] and start[CORE]["tools"] == [], start
    narrowed = await client.put(f"/chat/threads/{tid}/connectors", json={"off": [CRM]})
    assert narrowed.status_code == 200, narrowed.text
    assert (await settings(client, tid))["effective"]["toolsOff"] == ["lookup_account"]
    _, events = await send(client, tid, {"content": LOOKUP})
    assert calls(events) == [], "the CRM's tool is not offered, so the model cannot call it"
    later = (await new_thread(client))["id"]
    assert (await connectors(client, later))[CRM]["on"] is True
    _, events = await send(client, later, {"content": LOOKUP})
    assert calls(events) == ["lookup_account"], "a new chat has every connector on"


async def test_a_chat_cannot_turn_on_what_the_agent_or_team_does_not_have(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    for app in (CORE, "plugin:test.never"):
        refused = await client.put(f"/chat/threads/{tid}/connectors", json={"off": [app]})
        assert refused.status_code == 422 and refused.json()["error"]["details"] == {"appId": app}, refused.text
    assert "overrides" not in await settings(client, tid)


async def test_choosing_connectors_keeps_a_tool_switched_off_in_the_settings_panel(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    client, rt = stack
    wire(rt)
    MODULES["place_wire_hold"] = "mod_crm"  # one app with two tools
    try:
        tid = (await new_thread(client))["id"]
        await client.patch(f"/chat/threads/{tid}/settings", json={"toolsOff": ["place_wire_hold"]})
        kept = await client.put(f"/chat/threads/{tid}/connectors", json={"off": []})
        assert kept.status_code == 200, kept.text
        assert (await settings(client, tid))["effective"]["toolsOff"] == ["place_wire_hold"], "the panel's choice stays"
        await client.put(f"/chat/threads/{tid}/connectors", json={"off": [CRM]})
        assert (await settings(client, tid))["effective"]["toolsOff"] == ["lookup_account", "place_wire_hold"]
        back = await client.put(f"/chat/threads/{tid}/connectors", json={"off": []})
        assert back.json()["data"]["connectors"][0]["on"] is True, back.text
        assert (await settings(client, tid))["effective"]["toolsOff"] == [], "turned back on, every tool runs again"
    finally:
        MODULES["place_wire_hold"] = "mod_wires"


async def test_a_new_chats_connectors_are_listed_before_it_exists_and_its_first_message_keeps_the_choice(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    # Chat's home has no thread yet: the picker lists the agent's connectors, and the first message, sent after the
    # new chat takes the choice, offers no tool of an app left out.
    client, rt = stack
    wire(rt)
    listed = await client.get("/chat/connectors", params={"agentId": "ag_fraud"})
    assert listed.status_code == 200, listed.text
    before = {c["appId"]: (c["appState"], c["on"]) for c in listed.json()["data"]["connectors"]}
    assert before == {CRM: ("connected", True), WIRES: ("needs_sign_in", True), CORE: ("off", False)}, before
    tid = (await new_thread(client))["id"]
    assert (await client.put(f"/chat/threads/{tid}/connectors", json={"off": [CRM]})).status_code == 200
    _, events = await send(client, tid, {"content": LOOKUP})
    assert calls(events) == [], "the first message offers no tool of the app left out"


async def test_a_run_nobody_started_in_a_chat_ignores_a_chats_connectors(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    # A chat's choice lives on that chat; the same agent run as a workflow step or a schedule runs on its grants.
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    assert (await client.put(f"/chat/threads/{tid}/connectors", json={"off": [CRM]})).status_code == 200
    run = (await client.post("/v1/threads", json={"graph": "agent_wrapper", "metadata": {}})).json()["data"]["threadId"]
    body = {"input": {"agent_id": "ag_fraud", "message": LOOKUP, "kb_ids": ["kb_people"]}}
    res = await client.post(f"/v1/threads/{run}/runs/stream", json=body)
    assert res.status_code == 200, res.text
    assert '"lookup_account"' in res.text, "the unattended run still has the CRM's tool"


async def test_an_app_the_person_has_not_signed_in_to_is_in_the_sign_in_group_not_on(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    # tools-service answers the person's own state on an app each person signs in to; the picker shows it as it is,
    # never the team account's.
    client, rt = stack
    wire(rt)

    class Mine(Cards):
        async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
            rows = await super().cards(person, team)
            rows[0] = {**rows[0], "signIn": "person_or_team", "appState": "needs_sign_in"}
            return rows

    rt.app_states = Mine()
    tid = (await new_thread(client))["id"]
    crm = (await connectors(client, tid))[CRM]
    assert (crm["appState"], crm["personal"]) == ("needs_sign_in", True), crm
