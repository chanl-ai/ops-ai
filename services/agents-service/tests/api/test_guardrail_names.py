"""Guardrail names are unique per team, through the real route, by failure mode: a second team creating a guardrail
the first team already has is handed a renamed slug instead of its own; and one team holding two guardrails with the
same name is accepted, so a name no longer picks one guardrail."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app

OPS = person("james", "team_ops", "builder")
LENDING = person("lena", "team_lending", "builder")
RULE = {"name": "No investment advice", "topics": ["investment advice"], "message": "I can't give investment advice."}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


async def test_a_second_team_makes_a_guardrail_with_the_same_name_under_the_same_slug(client: AsyncClient) -> None:
    mine = ok(await client.post("/v1/guardrails", json=RULE, headers=OPS), 201)
    theirs = ok(await client.post("/v1/guardrails", json=RULE, headers=LENDING), 201)
    assert (mine["slug"], theirs["slug"]) == ("no-investment-advice", "no-investment-advice")
    assert mine["id"] != theirs["id"]


async def test_one_team_cannot_hold_two_guardrails_with_the_same_name(client: AsyncClient) -> None:
    ok(await client.post("/v1/guardrails", json=RULE, headers=OPS), 201)
    again = await client.post("/v1/guardrails", json=RULE, headers=OPS)
    assert again.status_code == 409 and again.json()["error"]["code"] == "name_taken", again.text
