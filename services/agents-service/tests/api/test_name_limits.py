"""A name a person types never crashes a save, through the real routes, by failure mode: a long name makes a slug wider
than its 120-wide column (a 500 on PostgreSQL), also once the uniqueness suffix is added; and a blank name, or one
holding a NUL or a line break, is saved instead of refused with 400."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app

OPS = person("james", "team_ops", "builder")
LONG = "Wire review " * 16  # 192 letters and spaces: inside the 200 the API allows, far over the 120-wide slug column
GUARDRAIL = {"topics": ["investment advice"], "message": "I can't give investment advice."}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


async def test_a_long_agent_name_makes_slugs_that_fit_the_column_even_when_taken(client: AsyncClient) -> None:
    slugs: list[str] = []
    for _ in range(3):
        made = ok(await client.post("/v1/agents", json={"name": LONG, "role": "Reviews wires"}, headers=OPS), 201)
        slugs.append(made["slug"])
    assert len(set(slugs)) == 3 and all(len(s) <= 120 and not s.endswith("-") for s in slugs), slugs


async def test_a_long_guardrail_name_makes_a_slug_that_fits_the_column(client: AsyncClient) -> None:
    made = ok(await client.post("/v1/guardrails", json={"name": LONG, **GUARDRAIL}, headers=OPS), 201)
    assert len(made["slug"]) <= 120
    too_long = await client.post("/v1/guardrails", json={"name": "x" * 201, **GUARDRAIL}, headers=OPS)
    assert too_long.status_code == 400, too_long.text


@pytest.mark.parametrize("bad", ["", "   ", "Wire\r\nreview", "Wire\x00review", "\t"])
async def test_a_blank_or_control_character_name_is_refused_with_400_by_every_route(
    client: AsyncClient, bad: str
) -> None:
    routes = {
        "/v1/agents": {"name": bad, "role": "Reviews wires"},
        "/v1/guardrails": {"name": bad, **GUARDRAIL},
    }
    for path, body in routes.items():
        r = await client.post(path, json=body, headers=OPS)
        assert r.status_code == 400 and r.json()["success"] is False, (path, r.text)


async def test_two_guardrail_names_equal_in_their_first_120_letters_say_so(client: AsyncClient) -> None:
    ok(await client.post("/v1/guardrails", json={"name": LONG + "one", **GUARDRAIL}, headers=OPS), 201)
    again = await client.post("/v1/guardrails", json={"name": LONG + "two", **GUARDRAIL}, headers=OPS)
    assert again.status_code == 409 and "first 120 letters" in again.json()["error"]["message"], again.text
