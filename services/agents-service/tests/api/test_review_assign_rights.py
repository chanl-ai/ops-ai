"""Assigning Human Tasks as a role that decides none, by failure mode: a viewer's assign answered 200 with every id
skipped, as if the request were fine, where a decision by them is refused 403."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity.testing import TEST_TOKEN_TTL_S
from ops_policy import mint
from tests.engine.test_lifecycle_rights import (  # noqa: F401  # a fixture
    BUILDER,
    PLATFORM,
    TENANT,
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


async def test_a_viewers_bulk_decision_is_refused_outright(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """A viewer's bulk decision answered 200 with every id skipped, where one decision by them is refused 403."""
    client, _ = stack
    body = {"ids": ["rev_missing"], "decision": "approved"}
    viewer = await client.post("/reviews/bulk-decision", json=body, headers=VIEWER)
    assert (viewer.status_code, viewer.json()["error"]["code"]) == (403, "role_required"), viewer.text
    builder = await client.post("/reviews/bulk-decision", json=body, headers=BUILDER)
    assert builder.status_code == 200 and builder.json()["data"]["skipped"][0]["id"] == "rev_missing", builder.text


async def test_a_reviewer_of_another_team_is_not_refused_a_bulk_decision_for_the_team_they_act_in(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    """The bulk gate read the acting team: a reviewer of Operations acting in Platform, where they hold no approve
    cell, was refused before any review of Operations was read."""
    client, _ = stack
    claims = {
        "sub": "rhea", "email": "rhea@harborpine.example", "name": "rhea", "kind": "person",
        "security_team": "team_security", "aud": ["agents"], "tenant_id": TENANT,
        "team_ids": ["team_platform", "team_ops"], "roles": {"team_platform": "viewer", "team_ops": "approver"},
    }  # fmt: skip
    both = {"Authorization": f"Bearer {mint(claims, PLATFORM, ttl_s=TEST_TOKEN_TTL_S)}", "X-Team-Id": "team_platform"}
    body = {"ids": ["rev_missing"], "decision": "approved"}
    across = await client.post("/reviews/bulk-decision", json=body, headers=both)
    assert across.status_code == 200 and across.json()["data"]["skipped"][0]["id"] == "rev_missing", across.text
