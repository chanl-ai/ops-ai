"""What blocks a team's delete or its workspace's close, for platform-service (c-529), by failure mode: a run in
progress or a live workflow missed, so a delete goes ahead with work still running; another team's runs or workflows
counted or named; a service naming no team, or a team in the query, read; a token without `workflows:view` answered."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.api.test_case_routes import (  # noqa: F401 - c is a fixture pytest finds by name
    OTHER_TEAM,
    c,  # pyright: ignore[reportUnusedImport]
    service,
    started_run,
)
from tests.engine.test_lifecycle_rights import BUILDER

URL = "/v1/teams/usage"
PLATFORM = service("platform", ["workflows:view"])


async def usage(client: AsyncClient, headers: dict[str, str], **params: Any) -> dict[str, Any]:
    r = await client.get(URL, headers=headers, params=params)
    assert r.status_code == 200, r.text
    return dict(r.json()["data"])


async def test_a_run_in_progress_and_a_live_workflow_of_the_team_are_counted(c: AsyncClient) -> None:  # noqa: F811
    before = await usage(c, PLATFORM)
    await started_run(c, BUILDER, "ops_check")
    after = await usage(c, PLATFORM)
    assert after["runsInProgress"] == before["runsInProgress"] + 1, (before, after)
    assert "Refund check" in after["liveWorkflows"], after


async def test_another_teams_runs_and_workflows_are_neither_counted_nor_named(c: AsyncClient) -> None:  # noqa: F811
    await started_run(c, OTHER_TEAM, "fraud_check")
    ours = await usage(c, PLATFORM)
    assert ours["runsInProgress"] == 0 and "Refund check" not in ours["liveWorkflows"], ours
    theirs = await usage(c, service("platform", ["workflows:view"], team="team_fraud"))
    assert theirs["runsInProgress"] == 1 and "Refund check" in theirs["liveWorkflows"], theirs


async def test_a_caller_naming_no_team_reads_nothing_and_a_query_team_is_ignored(c: AsyncClient) -> None:  # noqa: F811
    await started_run(c, OTHER_TEAM, "fraud_check")
    nobody = service("platform", ["workflows:view"], team=None)  # pyright: ignore[reportArgumentType]
    r = await c.get(URL, headers=nobody, params={"teamId": "team_fraud"})
    assert r.status_code == 401, r.text
    ours = await usage(c, PLATFORM, teamId="team_fraud")
    assert ours["runsInProgress"] == 0, ours


async def test_a_token_without_workflows_view_is_refused(c: AsyncClient) -> None:  # noqa: F811
    r = await c.get(URL, headers=service("platform", []))
    assert r.status_code == 403, r.text
