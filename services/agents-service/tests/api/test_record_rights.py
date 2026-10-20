"""The flags a detail response carries for what the caller may do with the record (c-186), by failure mode: a viewer
offered edit, delete or publish the route would refuse, or an admin shown View only on a record they may change. The
console reads these flags for its View only notice and buttons."""

from __future__ import annotations

from typing import Any

import pytest

from tests.api.test_action_roles import ADMIN, VIEWER
from tests.api.test_team_default_agent import Stack, stack  # noqa: F401  # pyright: ignore[reportUnusedImport]
from tests.api.test_widget_registry import LIMIT_CARD

FLAGS = ("canEdit", "canDelete", "canPublish")


async def flags(running: Stack, path: str, who: dict[str, str]) -> list[Any]:
    r = await running[0].get(path, headers=who)
    assert r.status_code == 200, r.text
    return [r.json()["data"].get(f) for f in FLAGS]


@pytest.mark.parametrize("path", ["/v1/agents/ag_branch", "/v1/workflows/dispute_email", "widget"])
async def test_a_viewer_may_not_change_a_record_and_an_admin_may(stack: Stack, path: str) -> None:  # noqa: F811
    if path == "widget":
        made = await stack[0].post("/v1/widgets", json=LIMIT_CARD, headers=ADMIN)
        assert made.status_code == 201, made.text
        path = f"/v1/widgets/{made.json()['data']['widgetId']}"
    assert await flags(stack, path, VIEWER) == [False, False, False]
    assert await flags(stack, path, ADMIN) == [True, True, True]
