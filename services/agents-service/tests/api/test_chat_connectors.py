"""A chat's connectors (the composer's picker), by failure mode: turning a connector off still offers its tools to the
model; a chat can turn on an app the agent was not granted, or one the team has off; the choice leaks into the next
chat; and choosing connectors wipes a tool the person switched off one by one in the settings panel."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, cast

import pytest
from httpx import AsyncClient

from ops_agents.activities.tool_directory import CatalogTools, OperationRef, ToolsUnavailable
from ops_agents.api.deps import Runtime
from tests.api.test_chat import new_thread, send
from tests.api.test_chat_on_graph import stack  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixture
from tests.api.test_chat_settings import LOOKUP, calls, settings

MODULES = {"lookup_account": "mod_crm", "place_wire_hold": "mod_wires"}
CRM, WIRES, CORE = "plugin:test.crm", "plugin:test.wires", "plugin:test.core"
LEDGER, GONE = "plugin:test.ledger", "plugin:test.gone"


class Modules:
    """The catalog's tools, each in the module of an app."""

    def __init__(self, rt: Runtime) -> None:
        self.inner = CatalogTools(rt.catalog)

    async def operations(self) -> list[OperationRef]:
        return [replace(o, module_id=MODULES.get(o.name, o.module_id)) for o in await self.inner.operations()]


class Cards:
    """The team's apps for the person as tools-service answers them: the CRM connected, Wires waiting for their own
    sign-in, Core banking off for the team, Ledger on with a broken auth config, and Old desk no longer installed."""

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        return [
            {
                "id": CRM, "kind": "plugin", "name": "CRM", "appState": "connected", "appGroup": "on",
                "moduleIds": ["mod_crm"],
            },
            {
                "id": WIRES, "kind": "plugin", "name": "Wires", "appState": "needs_sign_in", "appGroup": "needs_you",
                "signIn": "person", "moduleIds": ["mod_wires"],
            },
            {
                "id": CORE, "kind": "plugin", "name": "Core banking", "appState": "off", "appGroup": "needs_admin",
                "moduleIds": ["mod_core"],
            },
            {
                "id": LEDGER, "kind": "plugin", "name": "Ledger", "appState": "auth_config_broken",
                "appGroup": "needs_admin", "moduleIds": ["mod_crm"],
            },
            {
                "id": GONE, "kind": "plugin", "name": "Old desk", "appState": "removed", "appGroup": "gone",
                "moduleIds": ["mod_crm"],
            },
        ]  # fmt: skip

    async def accounts(
        self, person: str | None, team: str | None, app_id: str, *, usable: bool = False, name: str | None = None
    ) -> list[dict[str, Any]]:
        """The CRM has two accounts, the team's Retail desk (its default) and the person's own EU desk; every other
        app has one, which the picker does not list."""
        retail = {"name": "Retail desk", "identity": [{"label": "Org", "value": "x", "shown": "retail.crm.test"}]}
        eu = {"name": "EU desk", "identity": [{"label": "Org", "value": "y", "shown": "eu.crm.test"}], "own": True}
        rows: list[dict[str, Any]] = [{**retail, "default": True}, eu] if app_id == CRM else [{"name": "Only"}]
        rows = [r for r in rows if not (usable and r.get("own"))]
        return [r for r in rows if name is None or r["name"].casefold() == name.strip().casefold()]


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
    # What the person can use is the app's group: on and needs-you apps are on with their tools; an app an admin acts
    # on first is listed with no tools and off, even one whose tools the agent holds (Ledger); a gone app is not listed.
    assert {k: (v["on"], v["tools"] != []) for k, v in start.items()} == {
        CRM: (True, True),
        WIRES: (True, True),
        CORE: (False, False),
        LEDGER: (False, False),
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
    before = {c["appId"]: c["on"] for c in listed.json()["data"]["connectors"]}
    assert before == {CRM: True, WIRES: True, CORE: False, LEDGER: False}, before
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
    # tools-service answers the person's own sign-in as needs_you; the chat cannot leave it out, and Connect is theirs.
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    wires = (await connectors(client, tid))[WIRES]
    assert (wires["appGroup"], wires["personal"], wires["on"]) == ("needs_you", True, True), wires
    refused = await client.put(f"/chat/threads/{tid}/connectors", json={"off": [CORE]})
    assert refused.status_code == 422, refused.text


async def test_a_chat_lists_an_apps_accounts_and_keeps_the_one_picked(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
) -> None:
    """Failure modes: the picker shows no account for an app with two, so nobody can tell which org a chat uses; a
    pick is not kept on the chat; a name the app does not have is saved and sent."""
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    start = await connectors(client, tid)
    assert [a["name"] for a in start[CRM]["accounts"]] == ["Retail desk", "EU desk"], start[CRM]
    assert start[CRM]["account"] is None and start[WIRES]["accounts"] == [], start
    picked = await client.put(f"/chat/threads/{tid}/connectors", json={"off": [], "accounts": {CRM: "eu desk"}})
    assert picked.status_code == 200, picked.text
    assert (await connectors(client, tid))[CRM]["account"] == "EU desk"
    assert (await settings(client, tid))["overrides"]["accounts"] == {CRM: "EU desk"}
    refused = await client.put(f"/chat/threads/{tid}/connectors", json={"off": [], "accounts": {CRM: "Ghost desk"}})
    assert refused.status_code == 422 and refused.json()["error"]["code"] == "account_unknown", refused.text


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    """A structlog record's message is its fields."""
    msg: object = record.msg
    return cast(dict[str, Any], msg) if isinstance(msg, dict) else {}


class Unreachable:
    """tools-service not answering the app list."""

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        raise ToolsUnavailable("tools-service did not answer")


class Unrelated:
    """An app list with no app for any tool the agent holds."""

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        return [{"id": "plugin:test.other", "kind": "plugin", "name": "Other", "appState": "connected",
                 "appGroup": "on", "moduleIds": ["mod_other"]}]  # fmt: skip


@pytest.mark.parametrize(
    ("states", "reason", "cards"),
    [(Unreachable(), "tools_unavailable", 0), (None, "no_app_states", 0), (Unrelated(), "no_app_for_held_tools", 1)],
)
async def test_an_empty_picker_with_tools_held_logs_why(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    states: Any,
    reason: str,
    cards: int,
) -> None:
    # The picker reads "This agent uses no connector." for each of these; only the log says which one happened.
    client, rt = stack
    rt.tool_directory, rt.app_states = Modules(rt), states
    tid = (await new_thread(client))["id"]
    with caplog.at_level(logging.WARNING, logger="ops_agents.chat_connectors"):
        assert await connectors(client, tid) == {}
    lines = [f for f in map(_fields, caplog.records) if f.get("event") == "chat.connectors.empty"]
    assert len(lines) == 1, caplog.text
    line = lines[0]
    assert (line["reason"], line["cards"]) == (reason, cards), line
    assert str(line["agent"]).startswith("ag_") and str(line["team"]).startswith("team_"), line
    assert line["held"] >= 1, line


async def test_a_picker_with_apps_logs_nothing(
    stack: tuple[AsyncClient, Runtime],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, rt = stack
    wire(rt)
    tid = (await new_thread(client))["id"]
    with caplog.at_level(logging.WARNING, logger="ops_agents.chat_connectors"):
        assert await connectors(client, tid)
    assert "chat.connectors.empty" not in caplog.text
