"""Who reads another person's chat under the workspace's chatThreadsOwnerOnly policy, through the chat route and the
graph thread and event routes: on (the default), a role whose grid reads every chat still reads only its own; off, the
grid decides. The role is a custom one holding chat.view at `all`, as admins will once the grid gives them that cell."""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

import pytest

from ops_access import DEFAULT, Grant, Grids
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from tests.api.test_action_roles import VIEWER
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import BUILDER, PLATFORM, TENANT, person

# Vera's teammate in team_ops, holding the same role.
TEAMMATE = person("otto", "team_ops", "viewer")


def reader(policies: dict[str, Any] | None) -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": "rita",
        "email": "rita@harborpine.example",
        "name": "rita",
        "kind": "person",
        "security_team": "team_security",
        "aud": ["agents"],
        "tenant_id": TENANT,
        "team_ids": ["team_ops"],
        "access": {"team_ops": ["chat_reader"]},
        "perm_version": 1,
        **({"policies": policies} if policies is not None else {}),
    }
    return {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_ops"}


@pytest.fixture(autouse=True)
async def chat_reader_role(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fetch(_t: str, _v: int, _ids: list[str]) -> dict[str, Iterable[Grant]]:
        # Activity's chat rows are read by this role too, so it holds the activity list's cell.
        return {"chat_reader": [("chat", "view", "all"), ("activity", "view", "all")]}

    monkeypatch.setattr(DEFAULT, "grids", Grids(fetch=fetch))
    await DEFAULT.grids.load(TENANT, 1, ["chat_reader"])


@pytest.mark.parametrize("policies", [None, {"chatThreadsOwnerOnly": True}])
async def test_with_the_policy_on_only_the_starter_reads(stack: Stack, policies: dict[str, Any] | None) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    assert (await c.get(f"/chat/threads/{thread}", headers=VIEWER)).status_code == 200
    # Someone else's: no message, title or owner, and no failing request for a link the reader followed.
    sealed = await c.get(f"/chat/threads/{thread}", headers=reader(policies))
    assert sealed.status_code == 200 and sealed.json()["data"] == {"id": thread, "readable": False}, sealed.text
    assert (await c.get("/chat/threads/th_does_not_exist", headers=reader(policies))).status_code == 404


async def test_with_the_policy_off_the_grid_lets_a_reader_of_every_chat_read_it(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    r = await c.get(f"/chat/threads/{thread}", headers=reader({"chatThreadsOwnerOnly": False}))
    assert r.status_code == 200, r.text


async def test_a_link_opened_in_another_of_the_readers_teams_finds_the_conversation(stack: Stack) -> None:  # noqa: F811
    """A link opened while acting in another team answered not found, a refused request on a page that works: the
    reader's own conversation names its team so the console can switch, and a teammate's says only it is not theirs."""
    c, _ = stack
    thread = await chat(c, VIEWER)

    def in_two_teams(sub: str) -> dict[str, str]:
        claims: dict[str, Any] = {
            "sub": sub,
            "email": f"{sub}@harborpine.example",
            "name": sub,
            "kind": "person",
            "security_team": "team_security",
            "aud": ["agents"],
            "tenant_id": TENANT,
            "team_ids": ["team_ops", "team_fraud"],
            "roles": {"team_ops": "viewer", "team_fraud": "viewer"},
        }
        token = mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)
        return {"Authorization": f"Bearer {token}", "X-Team-Id": "team_fraud"}

    own = await c.get(f"/chat/threads/{thread}", headers=in_two_teams("vera"))
    assert own.status_code == 200, own.text
    assert {k: own.json()["data"][k] for k in ("id", "readable", "teamId")} == {
        "id": thread,
        "readable": False,
        "teamId": "team_ops",
    }, own.text
    other = await c.get(f"/chat/threads/{thread}", headers=in_two_teams("otto"))
    assert other.status_code == 200 and other.json()["data"] == {"id": thread, "readable": False}, other.text


async def chat_with_a_run(c: Any) -> tuple[str, str]:
    """Vera's chat with one finished turn, and that turn's run id."""
    thread = await chat(c, VIEWER)
    turn = await c.post(
        f"/v1/chat/threads/{thread}/messages",
        json={"content": "Hello"},
        headers={**VIEWER, "Accept": "text/event-stream"},
    )
    assert turn.status_code == 200, turn.text
    runs = await c.get(f"/v1/threads/{thread}/runs", headers=VIEWER)
    assert runs.status_code == 200 and runs.json()["data"], runs.text
    return thread, runs.json()["data"][0]["runId"]


@pytest.mark.parametrize("part", ["/state", "/runs", "/runs/{run}/events?follow=false"])
async def test_a_teammate_reads_no_part_of_a_chat_through_the_thread_routes(stack: Stack, part: str) -> None:  # noqa: F811
    c, _ = stack
    thread, run = await chat_with_a_run(c)
    url = f"/v1/threads/{thread}" + part.format(run=run)
    assert (await c.get(url, headers=VIEWER)).status_code == 200
    refused = await c.get(url, headers=TEAMMATE)
    assert refused.status_code == 404, refused.text
    # With the policy off a reader of every chat reads it: the grid decides, as on the chat route.
    assert (await c.get(url, headers=reader({"chatThreadsOwnerOnly": False}))).status_code == 200


async def test_a_teammate_lists_and_streams_no_chat_but_still_the_teams_workflows(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread, _ = await chat_with_a_run(c)
    made = await c.post("/v1/threads", json={"graph": "complex_workflow", "metadata": {}}, headers=BUILDER)
    assert made.status_code == 201, made.text
    workflow = made.json()["data"]["threadId"]

    def listed(r: Any) -> set[str]:
        assert r.status_code == 200, r.text
        return {t["threadId"] for t in r.json()["data"]["data"]}

    assert {thread, workflow} <= listed(await c.get("/v1/threads", headers=VIEWER))
    seen = listed(await c.get("/v1/threads", headers=TEAMMATE))
    assert workflow in seen and thread not in seen
    assert (await c.get(f"/v1/threads/{workflow}/state", headers=TEAMMATE)).status_code == 200

    def streamed(r: Any) -> set[str]:
        assert r.status_code == 200, r.text
        return {json.loads(line[5:])["threadId"] for line in r.text.splitlines() if line.startswith("data:")}

    assert thread in streamed(await c.get("/v1/events?follow=false", headers=VIEWER))
    assert thread not in streamed(await c.get("/v1/events?follow=false", headers=TEAMMATE))
