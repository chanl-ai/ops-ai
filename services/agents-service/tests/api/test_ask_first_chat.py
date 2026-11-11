"""An app's "Ask before changes" in chat, through the real routes, by failure mode:

- the asker answers their own card only where requesterMayDecide lets them; with it off the card offers them no Allow
  and a reviewer decides;
- an admin's own write is asked too, and waits like anyone's;
- Deny needs a reason, or runs the write anyway;
- "Allow for this chat" asks again in the same chat, or stops the asking in other chats too.

The policy and the flag come from tools-service (test_ask_before_changes there); here its answer is a fixed directory.
"""

from __future__ import annotations

import dataclasses
from collections.abc import AsyncIterator
from typing import Any, cast

import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from ops_agents.activities.tool_directory import CatalogTools, OperationRef
from ops_service_kit.settings import Settings
from tests.api.test_write_approval_policy import WRITE, _client, person  # pyright: ignore[reportPrivateUsage]
from tests.conftest import SEED, sse_events

_CATALOG_OPERATIONS = CatalogTools.operations


async def _asks_first(self: CatalogTools) -> list[OperationRef]:
    """The catalogue as tools-service answers it for a team whose app asks before changes: request_document runs
    without a reviewer, and asks the person in chat first."""
    return [
        dataclasses.replace(o, requires_approval=True, module_id="mod_desk") if o.name == "request_document" else o
        for o in await _CATALOG_OPERATIONS(self)
    ]


@pytest.fixture
async def chat(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    # The routes and the chat graph each read the directory; with no tools-service both read the catalogue.
    monkeypatch.setattr(CatalogTools, "operations", _asks_first)
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        seed_dir=SEED,
        environment="production",
        auth_mode="platform",
        platform_url="http://platform.invalid",
        review_key=SecretStr("r" * 40),
        secrets_key=SecretStr("ab" * 32),
    )
    async for c in _client(settings, platform=True):
        yield c


async def _ask(
    client: AsyncClient, who: dict[str, str], thread: str | None = None
) -> tuple[str, dict[str, Any] | None, str]:
    """Sends the write in `thread` (a new one when None): the thread, the approval card if one was drawn, and the
    message id."""
    if thread is None:
        made = await client.post("/chat/threads", json={"agentId": "ag_dispute", "kbIds": []}, headers=who)
        assert made.status_code == 201, made.text
        thread = str(made.json()["data"]["id"])
    sent = await client.post(
        f"/chat/threads/{thread}/messages", json={"content": WRITE}, headers={**who, "Accept": "text/event-stream"}
    )
    events = sse_events(sent.text)
    card = next((e["widget"] for e in events if e["type"] == "widget" and e["widget"]["kind"] == "approval"), None)
    return thread, card, str(events[0]["messageId"])


async def _parts(client: AsyncClient, who: dict[str, str], thread: str, kind: str) -> list[dict[str, Any]]:
    """The thread's tool calls (`toolCalls`) or widgets (`widgets`), as the person reads them."""
    messages = cast(
        list[dict[str, Any]], (await client.get(f"/chat/threads/{thread}", headers=who)).json()["data"]["messages"]
    )
    return [cast(dict[str, Any], x) for m in messages for x in cast(list[Any], m.get(kind) or [])]


async def _calls(client: AsyncClient, who: dict[str, str], thread: str) -> list[str]:
    return [str(c["status"]) for c in await _parts(client, who, thread, "toolCalls") if c["name"] == "request_document"]


def _act(thread: str, message: str, card: dict[str, Any]) -> str:
    return f"/chat/threads/{thread}/messages/{message}/widgets/{card['id']}/actions"


LOOSE = {"requesterMayDecide": True}


async def test_with_requester_may_decide_off_the_asker_cannot_allow_and_a_reviewer_does(chat: AsyncClient) -> None:
    james = person("usr_james", ["team_ops"], role="approver", policies={"requesterMayDecide": False})
    maya = person("usr_maya", ["team_ops"], role="admin", policies={"requesterMayDecide": False})
    thread, card, message = await _ask(chat, james)
    assert card is not None and card["askFirst"] is True and card["canDecide"] is False, card
    assert (await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=james)).status_code == 403
    allowed = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=maya)
    assert allowed.status_code == 200 and allowed.json()["data"]["state"] == "approved", allowed.text


async def test_with_requester_may_decide_on_the_asker_allows_their_own_write(chat: AsyncClient) -> None:
    james = person("usr_james", ["team_ops"], role="approver", policies=LOOSE)
    thread, card, message = await _ask(chat, james)
    assert card is not None and card["askFirst"] is True and card["canDecide"] is True, card
    allowed = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=james)
    assert allowed.status_code == 200 and allowed.json()["data"]["state"] == "approved", allowed.text
    assert (await _calls(chat, james, thread))[-1] == "success"


async def test_an_admin_is_asked_too(chat: AsyncClient) -> None:
    maya = person("usr_maya", ["team_ops"], role="admin", policies=LOOSE)
    thread, card, _ = await _ask(chat, maya)
    assert card is not None and card["askFirst"] is True, card
    states = [w["state"] for w in await _parts(chat, maya, thread, "widgets") if w["kind"] == "approval"]
    assert states == ["pending"], states


async def test_deny_needs_no_reason_and_runs_nothing(chat: AsyncClient) -> None:
    james = person("usr_james", ["team_ops"], role="approver", policies=LOOSE)
    thread, card, message = await _ask(chat, james)
    assert card is not None
    denied = await chat.post(_act(thread, message, card), json={"type": "reject", "reason": ""}, headers=james)
    assert denied.status_code == 200 and denied.json()["data"]["state"] == "rejected", denied.text
    outputs = [c.get("output") for c in await _parts(chat, james, thread, "toolCalls")]
    # The held call, then the model told the person said no; nothing the tool itself would answer.
    assert outputs[0] == {"status": "awaiting_approval"} and "chose Deny" in str(outputs[-1]), outputs


async def test_allow_for_this_chat_stops_asking_here_only(chat: AsyncClient) -> None:
    james = person("usr_james", ["team_ops"], role="approver", policies=LOOSE)
    thread, card, message = await _ask(chat, james)
    assert card is not None
    body = {"type": "approve", "forChat": True}
    assert (await chat.post(_act(thread, message, card), json=body, headers=james)).status_code == 200
    _, again, _ = await _ask(chat, james, thread)
    assert again is None, again
    assert (await _calls(chat, james, thread)).count("success") == 2
    _, other, _ = await _ask(chat, james)
    assert other is not None and other["askFirst"] is True, other
