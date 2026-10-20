"""The AI steps setting (c-298), by failure mode: a team that never turned AI steps on can add or save one; the step
list does not say why one is missing; one team's switch turns them on for another; an unread policy opens them."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ops_agents.api import ai_steps_gate
from ops_agents.api.platform_policies import PolicyUnread
from ops_agents.store.tenancy import tenant_scope
from tests.engine.test_lifecycle_rights import BUILDER

from .role_app import ok, role_app

AI_STEPS = {"ops.ai.classify", "ops.ai.summarise", "ops.ai.extractText", "ops.ai.draft"}


@pytest.fixture
async def c() -> AsyncIterator[AsyncClient]:
    async with role_app(TestModel()) as client:
        yield client


async def test_with_the_setting_off_the_ai_steps_are_listed_as_unavailable_and_saying_why(c: AsyncClient) -> None:
    types = {t["id"]: t for t in ok(await c.get("/v1/workflows/node-types", headers=BUILDER))}
    assert {t for t in AI_STEPS if types[t]["unavailable"] == ai_steps_gate.OFF} == AI_STEPS
    assert types["ops.ai.agent"]["unavailable"] is None


async def test_with_the_setting_off_a_workflow_using_one_is_not_saved(c: AsyncClient) -> None:
    definition: dict[str, Any] = {
        "schemaVersion": 2,
        "id": "triage_mail",
        "nodes": [
            {"id": "in", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
            {"id": "sort", "type": "ops.ai.summarise", "typeVersion": 1, "parameters": {"text": "$.input.body"}},
            {"id": "done", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "done"}},
            {"id": "failed", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": "failed"}},
        ],
        "connections": [
            {"from": {"node": "in", "port": "payload"}, "to": {"node": "sort", "port": "in"}},
            {"from": {"node": "sort", "port": "ok"}, "to": {"node": "done", "port": "in"}},
            {"from": {"node": "sort", "port": "error"}, "to": {"node": "failed", "port": "in"}},
        ],
    }
    res = await c.post("/v1/workflows/definitions", json={"definition": definition}, headers=BUILDER)
    assert res.status_code == 422 and res.json()["error"]["code"] == "ai_steps_off", res.text
    assert res.json()["error"]["details"]["nodes"] == ["sort"]


class Policies:
    def __init__(self, value: Any) -> None:
        self.found = value

    async def value(self, key: str) -> Any:
        assert key == ai_steps_gate.KEY
        if isinstance(self.found, Exception):
            raise self.found
        return self.found


@pytest.mark.parametrize(
    ("value", "team", "on"),
    [
        ({"team_ops": True}, "team_ops", True),
        ({"team_ops": True}, "team_fraud", False),
        ({}, "team_ops", False),
        (PolicyUnread("platform-service is down"), "team_ops", False),
    ],
)
async def test_only_the_team_that_turned_it_on_has_ai_steps(value: Any, team: str, on: bool) -> None:
    rt: Any = SimpleNamespace(policies=Policies(value))
    with tenant_scope("acme"):
        assert await ai_steps_gate.allowed(rt, team) is on
