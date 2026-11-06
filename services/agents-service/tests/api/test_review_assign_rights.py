"""Assigning Human Tasks as a role that decides none, by failure mode: a viewer's assign answered 200 with every id
skipped, as if the request were fine, where a decision by them is refused 403."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.engine.test_lifecycle_rights import (  # noqa: F401  # a fixture
    BUILDER,
    person,
    stack,  # pyright: ignore[reportUnusedImport]
)

VIEWER = person("vera", "team_ops", "viewer")


async def test_a_viewer_is_refused_and_a_builder_gets_a_result_per_id(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    client, _ = stack
    viewer = await client.post("/reviews/assign", json={"ids": ["rev_missing"]}, headers=VIEWER)
    assert (viewer.status_code, viewer.json()["error"]["code"]) == (403, "role_required"), viewer.text
    builder = await client.post("/reviews/assign", json={"ids": ["rev_missing"]}, headers=BUILDER)
    assert builder.status_code == 200 and builder.json()["data"]["skipped"][0]["id"] == "rev_missing", builder.text
