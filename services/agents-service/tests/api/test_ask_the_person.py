"""The answer tools-service hands agents (`answer`, `reviewerRole` on a grantable operation) decides who may allow a
chat write, through the real chat routes, by failure mode: "ask the person" refusing the person who asked because they
lack the approve cell or the team keeps self-approval off, or letting someone else allow their card; and "ask a
reviewer" letting an Admin outside the chosen role, or the asker, allow it.

tools-service is a fake that serves the wire rows (GET /v1/grantable-operations); the policy behind them is tested
there."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from ops_agents.activities.tool_directory import CatalogTools, OperationRef, ToolsOperations
from ops_agents.store.tenancy import current_tenant
from ops_identity import ServiceClient, dev_service_signer
from ops_service_kit.settings import Settings
from tests.api.test_ask_first_chat import _act, _ask  # pyright: ignore[reportPrivateUsage]
from tests.api.test_write_approval_policy import _client, person  # pyright: ignore[reportPrivateUsage]
from tests.conftest import SEED
from tests.unit.test_tool_directory import Clock, Tools

NO_SELF = {"requesterMayDecide": False}
_CATALOG = CatalogTools.operations


def _row(o: OperationRef, answer: dict[str, Any]) -> dict[str, Any]:
    asks = o.name == "request_document"
    return {
        "name": o.name,
        "description": o.description,
        "access": o.access,
        "inputSchema": o.input_schema,
        "requiresApproval": asks or o.requires_approval,
        "moduleId": "mod_desk" if asks else o.module_id,
        "moduleName": o.module_name,
        **(answer if asks else {}),
    }


Chat = Callable[[dict[str, Any]], AsyncIterator[AsyncClient]]


@pytest.fixture
def answered(monkeypatch: pytest.MonkeyPatch) -> Callable[[dict[str, Any]], AsyncIterator[AsyncClient]]:
    async def chat(answer: dict[str, Any]) -> AsyncIterator[AsyncClient]:
        async def operations(self: CatalogTools) -> list[OperationRef]:
            tools = Tools({current_tenant(): [_row(o, answer) for o in await _CATALOG(self)]})
            http = httpx.AsyncClient(transport=httpx.MockTransport(tools.handler), base_url="http://tools")
            service = ServiceClient(http, dev_service_signer(), "agents", "tools", tenant=current_tenant)
            return await ToolsOperations(service, ttl_s=30, clock=Clock()).operations()

        monkeypatch.setattr(CatalogTools, "operations", operations)
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

    return chat


async def test_ask_the_person_is_answered_by_the_asker_alone_with_no_approve_cell_and_self_approval_off(
    answered: Chat,
) -> None:
    async for chat in answered({"answer": "person", "reviewerRole": None, "source": "team"}):
        vera = person("usr_vera", ["team_ops"], role="viewer", policies=NO_SELF)
        maya = person("usr_maya", ["team_ops"], role="admin", policies=NO_SELF)
        thread, card, message = await _ask(chat, vera)
        assert card is not None and card["canDecide"] is True, card
        own = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=vera)
        assert own.status_code == 200 and own.json()["data"]["state"] == "approved", own.text
        thread, card, message = await _ask(chat, vera)
        assert card is not None
        other = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=maya)
        assert other.status_code == 403, other.text


async def test_ask_a_reviewer_is_decided_by_the_role_and_never_by_the_asker(answered: Chat) -> None:
    async for chat in answered({"answer": "reviewer", "reviewerRole": "compliance", "source": "team"}):
        james = person("usr_james", ["team_ops"], role="approver", policies=NO_SELF)
        maya = person("usr_maya", ["team_ops"], role="admin", policies=NO_SELF)
        thread, card, message = await _ask(chat, james)
        assert card is not None and card["askFirst"] is False and card["canDecide"] is False, card
        outside = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=maya)
        own = await chat.post(_act(thread, message, card), json={"type": "approve"}, headers=james)
        assert (outside.status_code, own.status_code) == (403, 403), (outside.text, own.text)
