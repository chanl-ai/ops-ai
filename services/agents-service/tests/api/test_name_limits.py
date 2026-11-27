"""A name a person types never crashes a save, through the real routes, by failure mode: a long name makes a slug wider
than its 120-wide column (a 500 on PostgreSQL), also once the uniqueness suffix is added; and a blank name, or one
holding a NUL or a line break, is saved instead of refused with 400."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
from httpx import AsyncClient

from ops_service_kit.names import LINE_BREAK
from tests.conftest import scripted_model

from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app

OPS = person("james", "team_ops", "builder")
LONG = "Wire review " * 16  # 192 letters and spaces: inside the 200 the API allows, far over the 120-wide slug column
GUARDRAIL = {"topics": ["investment advice"], "message": "I can't give investment advice."}


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(scripted_model()) as c:
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


@pytest.mark.parametrize("bad", ["", "   ", "Wire\x00review", "\t", "\r\n", "\u200b", "\u200b\u202e "])
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


async def test_a_name_with_a_line_break_is_refused_with_one_message_and_a_tab_is_a_space(client: AsyncClient) -> None:
    messages: set[str] = set()
    for path, body in {
        "/v1/agents": {"name": "Wire\r\nreview", "role": "r"},
        "/v1/guardrails": {"name": "Wire\nreview", **GUARDRAIL},
        "/v1/skills": {
            "name": "Wire\nreview",
            "useWhen": "a wire needs review",
            "instructions": "Review it.",
            "ownerTeam": "team_ops",
        },
    }.items():
        r = await client.post(path, json=body, headers=OPS)
        assert r.status_code == 400, (path, r.text)
        messages.add(str(r.json()["error"]["message"]))
    assert all(m.endswith(LINE_BREAK[1]) for m in messages), messages
    made = ok(await client.post("/v1/agents", json={"name": "  Wire\treview   desk ", "role": "r"}, headers=OPS), 201)
    assert made["name"] == "Wire review desk"


async def test_names_that_differ_only_in_non_latin_letters_get_distinct_slugs(client: AsyncClient) -> None:
    one = ok(await client.post("/v1/guardrails", json={"name": "QA 高风险交易审查", **GUARDRAIL}, headers=OPS), 201)
    two = ok(await client.post("/v1/guardrails", json={"name": "QA 客户投诉处理", **GUARDRAIL}, headers=OPS), 201)
    agent = ok(await client.post("/v1/agents", json={"name": "Проверка переводов", "role": "r"}, headers=OPS), 201)
    assert one["slug"] != two["slug"] and one["slug"].startswith("qa-"), (one["slug"], two["slug"])
    assert agent["slug"] not in ("", "agent"), agent["slug"]
