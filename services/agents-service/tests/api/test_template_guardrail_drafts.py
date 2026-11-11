"""A guardrail copy's update follows the agent rule (definitions-and-versions.md, ADR-0018): while the newest version
is an open draft the update merges into that draft; a draft a publish request names is never rewritten, so the update
opens the next version. Each test is one failure mode; tools-service is faked at its client as in
test_template_install."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic_ai.models.test import TestModel

from ops_agents.api.agent_registry import registry

from .role_app import ok, role_app
from .test_template_guardrails import PACK, advice
from .test_template_install import wire
from .test_template_update import OPS


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    async with role_app(TestModel()) as c:
        yield c


async def _copy_then_update(client: AsyncClient, gid_path: str, gid: str) -> dict[str, Any]:
    wire(client, [advice(2, "investment advice", "legal advice")])
    review = ok(await client.get(gid_path, headers=OPS))
    ok(await client.post(gid_path, json={"expect": review["expect"]}, headers=OPS))
    return ok(await client.get(f"/v1/guardrails/{gid}", headers=OPS))


async def test_an_update_merges_into_the_open_draft_without_a_new_version(client: AsyncClient) -> None:
    wire(client, [advice()])
    gid = ok(await client.post(f"/v1/resources/{PACK}:no-advice/copies", json={}, headers=OPS), 201)["copy"]["recordId"]
    held = await _copy_then_update(client, f"/v1/resources/{PACK}:no-advice/copies/{gid}/update", gid)
    assert [v["version"] for v in held["versions"]] == [1], held["versions"]
    assert set(held["versions"][0]["config"]["topics"]) == {"investment advice", "legal advice"}


async def test_an_update_never_rewrites_a_draft_a_publish_request_names(client: AsyncClient) -> None:
    wire(client, [advice()])
    gid = ok(await client.post(f"/v1/resources/{PACK}:no-advice/copies", json={}, headers=OPS), 201)["copy"]["recordId"]
    rt: Any = client._transport.app.state.runtime  # type: ignore[attr-defined]
    # A review the owner has not decided yet: the request that names v1 is what a reviewer is reading.
    await registry(rt).open_request(
        "guardrail", gid, 1, note="", by="ops@example.com", body={"guardrailId": gid}, approved=False
    )
    held = await _copy_then_update(client, f"/v1/resources/{PACK}:no-advice/copies/{gid}/update", gid)
    by_version = {v["version"]: v["config"]["topics"] for v in held["versions"]}
    assert by_version[1] == ["investment advice"], by_version
    assert set(by_version[2]) == {"investment advice", "legal advice"}, by_version
