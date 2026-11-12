"""Guardrails from a template, through the real routes, by failure mode: a guardrail template cannot be added at all;
the copy lands published or takes the template's id, so a second team's copy collides with the first; and an update
loosens the guardrail: a topic the team added is dropped when the template changes the list, so the team stops
blocking what it chose to block.

tools-service is faked at its client, as in test_template_install."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ..engine.test_lifecycle_rights import person
from .role_app import ok, role_app
from .test_template_install import wire
from .test_template_update import OPS

LENDING = person("lena", "team_lending", "builder")
PACK = "plugin:test.core"


def advice(version: int = 1, *topics: str) -> dict[str, Any]:
    return {
        "source": PACK,
        "plugin": {"id": "test.core", "title": "core", "version": "1"},
        "kind": "guardrail",
        "id": "no-advice",
        "version": version,
        "title": "No advice",
        "requires": {"tools": [], "bind": []},
        "digest": f"g{version}" * 32,
        "body": {
            "name": "No advice",
            "kind": "blocked_topics",
            "topics": list(topics or ("investment advice",)),
            "message": "I can't advise on that.",
        },
    }


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


async def test_each_team_adds_the_guardrail_as_its_own_unpublished_copy(client: AsyncClient) -> None:
    wire(client, [advice()])
    made: list[dict[str, Any]] = []
    for who in (OPS, LENDING):
        copy = ok(await client.post(f"/v1/resources/{PACK}:no-advice/copies", json={}, headers=who), 201)["copy"]
        made.append(copy)
        held = ok(await client.get(f"/v1/guardrails/{copy['recordId']}", headers=who))
        assert held["name"] == "No advice" and held["publishedVersion"] is None
        assert held["config"]["topics"] == ["investment advice"]
    assert made[0]["recordId"] != made[1]["recordId"] and made[0]["recordId"] != "no-advice"


async def test_an_update_keeps_a_topic_the_team_added_beside_the_templates_new_one(client: AsyncClient) -> None:
    wire(client, [advice()])
    gid = ok(await client.post(f"/v1/resources/{PACK}:no-advice/copies", json={}, headers=OPS), 201)["copy"]["recordId"]
    ok(await client.patch(f"/v1/guardrails/{gid}", json={"topics": ["investment advice", "tax advice"]}, headers=OPS))
    wire(client, [advice(2, "investment advice", "legal advice")])
    path = f"/v1/resources/{PACK}:no-advice/copies/{gid}/update"
    review = ok(await client.get(path, headers=OPS))
    ok(await client.post(path, json={"expect": review["expect"]}, headers=OPS))
    newest = ok(await client.get(f"/v1/guardrails/{gid}", headers=OPS))
    topics = next(v for v in newest["versions"] if v["version"] == newest["version"])["config"]["topics"]
    assert set(topics) == {"investment advice", "tax advice", "legal advice"}, topics
