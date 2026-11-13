"""POST /v1/runs from a service for the person its X-Acting-For token names (tools-service, for a person signed in to an
MCP link): one test per way it could start a run that person may not start, start one for nobody, or let the run's
writes skip the person who must approve them."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from httpx import AsyncClient

from ops_agents.store.tenancy import LOCAL_TENANT, tenant_scope
from ops_engine.store.tables import engine_runs as runs
from ops_identity import ACTING_FOR_HEADER, ActingForTokens, dev_service_signer, mint_service_token

BASIC = Path(__file__).parents[1] / "fixtures" / "engine" / "basic.yaml"
TEAM = "team_ops"
PERSON = "maya.okafor@bank.test"


async def _published(client: AsyncClient) -> None:
    assert (await client.post("/v1/workflows/definitions", json={"yaml": BASIC.read_text()})).status_code == 201
    assert (await client.post("/v1/workflows/definitions/refund_check/publish-requests", json={})).status_code == 201


async def _as_tools(scopes: list[str], *, acting: bool) -> dict[str, str]:
    """tools-service's token holding only the cells the person holds, and the person it acts for."""
    signer = dev_service_signer()
    token = mint_service_token(
        signer, service="tools", audience="agents", tenant_id=LOCAL_TENANT, scopes=scopes, team_id=TEAM
    )
    headers = {"Authorization": f"Bearer {token}"}
    if acting:
        people = ActingForTokens.for_dev(signer, service="tools", audience="agents")
        headers[ACTING_FOR_HEADER] = await people.token(tenant_id=LOCAL_TENANT, email=PERSON, team_id=TEAM)
    return headers


BODY = {"workflowId": "refund_check", "input": {"ticketId": "T-1"}, "mode": "live"}


async def test_a_service_starts_a_run_as_the_person_and_its_writes_still_wait_for_an_approver(
    client: AsyncClient,
) -> None:
    await _published(client)
    r = await client.post("/v1/runs", json=BODY, headers=await _as_tools(["workflows:run"], acting=True))
    assert r.status_code == 202, r.text
    run_id = r.json()["data"]["runId"]
    app = cast(Any, client)._transport.app
    with tenant_scope(LOCAL_TENANT):
        async with app.state.runtime.db.connect() as c:
            row = (await c.execute(sa.select(runs).where(runs.c.id == run_id))).mappings().one()
    assert PERSON in str(row["created_by"]), "the run records the person, not the service"
    assert row["started_by_approver"] is False, "a run started over MCP never approves its own writes"


async def test_a_person_without_the_run_right_starts_nothing(client: AsyncClient) -> None:
    await _published(client)
    r = await client.post("/v1/runs", json=BODY, headers=await _as_tools([], acting=True))
    assert r.status_code == 403, r.text


async def test_a_service_acting_for_nobody_starts_nothing(client: AsyncClient) -> None:
    await _published(client)
    r = await client.post("/v1/runs", json=BODY, headers=await _as_tools(["workflows:run"], acting=False))
    assert r.status_code == 403, r.text
