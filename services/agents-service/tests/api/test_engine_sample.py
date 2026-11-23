"""What a step receives, by failure mode: another team's run of a shared workflow feeds the sample; a personal value
shows unmasked; a huge value floods the sheet; a step deleted since the run still lists; a step added to the working
copy since the last version has no fields to pick. Each goes through `GET …/definitions/{id}/sample`, the one route
the step sheet reads."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.store.tenancy import tenant_scope
from ops_engine.store.tables import engine_runs, engine_steps
from tests.engine.test_lifecycle import definition
from tests.engine.test_lifecycle_rights import BUILDER, TENANT, person, stack, unowned_live

__all__ = ["stack"]

OTHER_TEAM = person("olu", "team_claims", "builder")
WF = "/v1/workflows/definitions/shared_refunds"


async def _ran(engine: AsyncEngine, run_id: str, team: str, outputs: dict[str, Any], *, at: str) -> None:
    """A finished run of the shared workflow by `team`, each step's output as given."""
    async with engine.begin() as c:
        await c.execute(
            engine_runs.insert().values(
                id=run_id,
                tenant_id=TENANT,
                team_id=team,
                workflow_id="shared_refunds",
                version=1,
                digest="d" * 64,
                run_key=run_id,
                mode="test",
                status="succeeded",
                created_by="seed",
                created_at=at,
                updated_at=at,
            )
        )
        for node, out in outputs.items():
            await c.execute(
                engine_steps.insert().values(
                    run_id=run_id,
                    node_id=node,
                    iteration=0,
                    attempt=1,
                    tenant_id=TENANT,
                    status="succeeded",
                    effects="none",
                    key=f"{run_id}:{node}",
                    port="out",
                    output=out,
                    started_at=at,
                    finished_at=at,
                )
            )


@pytest.fixture
async def shared(stack: tuple[AsyncClient, AsyncEngine]) -> AsyncIterator[tuple[AsyncClient, AsyncEngine]]:
    c, engine = stack
    with tenant_scope(TENANT):
        await unowned_live(engine, "shared_refunds", by="seed")
    yield c, engine


def _fields(body: dict[str, Any], step: str) -> dict[str, dict[str, Any]]:
    found = next(s for s in body["steps"] if s["id"] == step)
    return {f["name"]: f for f in found["fields"]}


async def test_only_the_callers_team_run_feeds_a_shared_workflows_sample(
    shared: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, engine = shared
    # The other team's run is newer, so a sample not held to the acting team would pick it.
    await _ran(engine, "run_ops", "team_ops", {"fields": {"amount": 40}}, at="2026-11-20T10:00:00Z")
    await _ran(engine, "run_claims", "team_claims", {"fields": {"amount": 999}}, at="2026-11-21T10:00:00Z")
    got = await c.get(f"{WF}/sample", params={"step": "small"}, headers=BUILDER)
    assert got.status_code == 200, got.text
    body = got.json()["data"]
    assert body["run"]["id"] == "run_ops"
    assert _fields(body, "fields")["amount"]["sample"] == "40"
    assert _fields(body, "fields")["amount"]["path"] == "$.nodes.fields.out.amount"
    theirs = (await c.get(f"{WF}/sample", params={"step": "small"}, headers=OTHER_TEAM)).json()["data"]
    assert theirs["run"]["id"] == "run_claims"
    # A member who may not view workflows reads no run values.
    no_view = person("wes", "team_ops", "chat_user")
    assert (await c.get(f"{WF}/sample", params={"step": "small"}, headers=no_view)).status_code == 403


async def test_a_personal_value_is_masked_and_a_huge_one_is_cut(shared: tuple[AsyncClient, AsyncEngine]) -> None:
    c, engine = shared
    outputs = {"fields": {"amount": "Refund alex.moreau@harborpine.example", "note": "x" * 5000}}
    await _ran(engine, "run_ops", "team_ops", outputs, at="2026-11-20T10:00:00Z")
    body = (await c.get(f"{WF}/sample", params={"step": "small"}, headers=BUILDER)).json()["data"]
    fields = _fields(body, "fields")
    assert "alex.moreau" not in fields["amount"]["sample"]
    # An open shape lists the fields the run gave as well as the ones the settings name.
    assert len(fields["note"]["sample"]) <= 501 and fields["note"]["sample"].endswith("…")


async def test_earlier_steps_only_from_the_working_copy_and_a_deleted_step_is_left_out(
    shared: tuple[AsyncClient, AsyncEngine],
) -> None:
    c, engine = shared
    await _ran(engine, "run_ops", "team_ops", {"fields": {"amount": 40}, "gone": {"x": 1}}, at="2026-11-20T10:00:00Z")
    # A step added in the working copy since version 1: it has fields to pick before the next version.
    d = definition("shared_refunds")
    d["nodes"].append(
        {
            "id": "extra",
            "type": "ops.data.set",
            "typeVersion": 1,
            "name": "Extra",
            "parameters": {"values": {"why": "x"}},
        }
    )
    d["connections"].append({"from": {"node": "fields", "port": "out"}, "to": {"node": "extra", "port": "in"}})
    d["connections"].append({"from": {"node": "extra", "port": "out"}, "to": {"node": "big", "port": "in"}})
    base = (await c.get(WF, headers=BUILDER)).json()["data"]["saveBase"]
    body = {"definition": d, "baseVersion": base["version"], "baseDigest": base["digest"]}
    assert (await c.put(f"{WF}/working-copy", json=body, headers=BUILDER)).status_code == 200
    got = (await c.get(f"{WF}/sample", params={"step": "big"}, headers=BUILDER)).json()["data"]
    assert [s["id"] for s in got["steps"]] == ["start", "fields", "extra"]
    assert _fields(got, "extra")["why"]["sample"] is None
    assert got["given"]["id"] == "big" and got["given"]["fields"]
    assert got["saved"] is True
    # The first step has nothing before it; a step only the browser holds is not saved yet.
    assert (await c.get(f"{WF}/sample", params={"step": "start"}, headers=BUILDER)).json()["data"]["steps"] == []
    unsaved = (await c.get(f"{WF}/sample", params={"step": "drawn_only"}, headers=BUILDER)).json()["data"]
    assert unsaved["saved"] is False and unsaved["steps"] == []
