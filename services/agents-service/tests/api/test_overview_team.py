"""The Overview's lists stay in the acting team (c-552): a run or a case due in one team never shows on another team's
Overview, read as people who each hold only their own team."""

from __future__ import annotations

from httpx import AsyncClient

from tests.api.test_case_routes import (
    DISPUTE,
    OTHER_TEAM,
    c,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
    started_run,
)
from tests.engine.test_lifecycle_rights import BUILDER

PAST = "2020-01-01T00:00:00.000Z"


async def due_case(c: AsyncClient, who: dict[str, str], subject: str) -> str:  # noqa: F811
    made = await c.post("/v1/cases", json=DISPUTE | {"subject": subject}, headers=who)
    assert made.status_code == 201, made.text
    case_id = str(made.json()["data"]["id"])
    patched = await c.patch(f"/v1/cases/{case_id}", json={"resolutionDueAt": PAST}, headers=who)
    assert patched.status_code == 200, patched.text
    return case_id


async def test_another_teams_runs_and_cases_stay_off_the_overview(c: AsyncClient) -> None:  # noqa: F811
    ours_run = await started_run(c, BUILDER, "ops_overview_run")
    theirs_run = await started_run(c, OTHER_TEAM, "fraud_overview_run")
    ours_case = await due_case(c, BUILDER, "Ops case due")
    theirs_case = await due_case(c, OTHER_TEAM, "Fraud case due")

    ops = (await c.get("/v1/overview", headers=BUILDER)).json()["data"]
    fraud = (await c.get("/v1/overview", headers=OTHER_TEAM)).json()["data"]

    assert ours_run in {r["id"] for r in ops["runsInFlight"]}, ops["runsInFlight"]
    assert theirs_run not in {r["id"] for r in ops["runsInFlight"]}, "the fraud team's run is on the ops Overview"
    assert theirs_run in {r["id"] for r in fraud["runsInFlight"]}, fraud["runsInFlight"]
    assert ours_case in {r["id"] for r in ops["casesDue"]}, ops["casesDue"]
    assert theirs_case not in {r["id"] for r in ops["casesDue"]}, "the fraud team's case is on the ops Overview"
    assert (ops["counts"]["runsInFlight"], ops["counts"]["casesDue"]) == (1, 1), ops["counts"]
