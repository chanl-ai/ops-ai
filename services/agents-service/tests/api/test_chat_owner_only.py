"""Who reads another person's chat under the workspace's chatThreadsOwnerOnly policy (c-186), through the chat route:
on (the default), a role whose grid reads every chat still reads only its own; off, the grid decides. The role is a
custom one holding chat.view at `all`, as admins will once the grid gives them that cell."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import pytest

from ops_access import DEFAULT, Grant, Grids
from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from tests.api.test_action_roles import VIEWER
from tests.api.test_memory import chat
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.engine.test_lifecycle_rights import PLATFORM, TENANT


def reader(policies: dict[str, Any] | None) -> dict[str, str]:
    claims: dict[str, Any] = {
        "sub": "rita",
        "email": "rita@harborpine.example",
        "name": "rita",
        "kind": "person",
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
        return {"chat_reader": [("chat", "view", "all")]}

    monkeypatch.setattr(DEFAULT, "grids", Grids(fetch=fetch))
    await DEFAULT.grids.load(TENANT, 1, ["chat_reader"])


@pytest.mark.parametrize("policies", [None, {"chatThreadsOwnerOnly": True}])
async def test_with_the_policy_on_only_the_starter_reads(stack: Stack, policies: dict[str, Any] | None) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    assert (await c.get(f"/chat/threads/{thread}", headers=VIEWER)).status_code == 200
    assert (await c.get(f"/chat/threads/{thread}", headers=reader(policies))).status_code == 404


async def test_with_the_policy_off_the_grid_lets_a_reader_of_every_chat_read_it(stack: Stack) -> None:  # noqa: F811
    c, _ = stack
    thread = await chat(c, VIEWER)
    r = await c.get(f"/chat/threads/{thread}", headers=reader({"chatThreadsOwnerOnly": False}))
    assert r.status_code == 200, r.text
