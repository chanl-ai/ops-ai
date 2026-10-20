"""A tool module's detail says what the caller may do with it (c-186), by failure mode: a viewer shown Edit or Delete
it would be refused, and an admin shown View only for a module they may change. Each flag runs the check its route
runs, so the console's buttons follow it."""

from __future__ import annotations

from typing import Any

import httpx

from .test_provisioned_records import tools  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
from .test_review_decisions import person


async def test_a_viewer_may_not_change_a_module_and_an_admin_may(
    tools: tuple[httpx.AsyncClient, dict[str, dict[str, str]]],  # noqa: F811
    tenant: str,
) -> None:
    c, people = tools
    viewer = person(tenant, "Vera Lane", {"team_platform": "viewer"})
    module: dict[str, Any] = (await c.get("/v1/tool-modules", headers=people["ana"])).json()["data"]["data"][0]
    url = f"/v1/tool-modules/{module['id']}"
    seen = (await c.get(url, headers=viewer)).json()["data"]
    owned = (await c.get(url, headers=people["ana"])).json()["data"]
    flags = ("canEdit", "canDelete", "canPublish")
    assert [seen[f] for f in flags] == [False, False, False], seen
    assert [owned[f] for f in flags] == [True, True, True], owned
    edit = await c.patch(url, json={"description": "Changed"}, headers=viewer)
    assert edit.status_code == 403, "the flag says what the route does"
