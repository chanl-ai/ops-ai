"""A publish review's clock and its decision, by failure mode: a review that reads the same time left however long
it has waited, one never listed as overdue, and a decided review that does not say who decided it, when or why."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_agents.api.agent_registry import review_view
from ops_agents.api.review_sla import PlatformReviewSla
from ops_agents.store.agent_registry import publish_requests
from ops_agents.store.tenancy import current_tenant, tenant_scope
from ops_identity import ServiceClient, dev_service_signer
from tests.api.test_action_roles import (
    BUILDER,
    REVIEWER,
    stack,  # noqa: F401  # pyright: ignore[reportUnusedImport] - a fixture
)


async def _requested(c: AsyncClient, name: str) -> str:
    made = (await c.post("/v1/agents", json={"name": name, "role": "Answers"}, headers=BUILDER)).json()["data"]
    req = await c.post(
        f"/v1/agents/{made['id']}/publish-requests", json={"version": made["version"], "note": "go"}, headers=BUILDER
    )
    assert req.status_code == 201, req.text
    return str(req.json()["data"]["id"])


async def _review(c: AsyncClient, rid: str) -> dict[str, Any]:
    r = await c.get(f"/reviews/{rid}", headers=REVIEWER)
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_the_clock_counts_down_from_the_request_and_goes_overdue(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, engine = stack
    fresh, old = await _requested(c, "Branch Desk"), await _requested(c, "Branch Counter")
    asked = (datetime.now(UTC) - timedelta(hours=9)).isoformat()
    async with engine.begin() as conn:
        await conn.execute(sa.update(publish_requests).where(publish_requests.c.id == old).values(created_at=asked))
    assert 470 <= (await _review(c, fresh))["slaMinutes"] <= 480
    assert (await _review(c, old))["slaMinutes"] <= -59, "nine hours on an eight-hour clock is an hour overdue"
    overdue = (await c.get("/reviews", params={"view": "overdue"}, headers=REVIEWER)).json()["data"]["data"]
    assert old in {r["id"] for r in overdue} and fresh not in {r["id"] for r in overdue}


async def test_a_decided_review_says_who_decided_it_when_and_why(
    stack: tuple[AsyncClient, AsyncEngine],  # noqa: F811
) -> None:
    c, _ = stack
    rid = await _requested(c, "Branch Help")
    body = {"decision": "rejected", "reason": "Name the escalation path first."}
    decided = await c.post(f"/v1/publish-requests/{rid}/decision", json=body, headers=REVIEWER)
    assert decided.status_code == 200, decided.text
    review = await _review(c, rid)
    assert review["decidedBy"] == "maya@northfield.example", review
    assert review["decidedAt"] and review["decisionReason"] == body["reason"]
    assert review["slaMinutes"] is None, "a decided review has no time left to count"


async def test_the_workspace_review_deadline_moves_the_clock() -> None:
    """reviewSlaHours set to 24 in platform-service: a new review has a day left, not eight hours, and listing many
    reviews reads the policy once."""
    reads: list[str] = []

    async def platform(request: httpx.Request) -> httpx.Response:
        reads.append(request.url.path)
        return httpx.Response(200, json={"success": True, "data": {"key": "reviewSlaHours", "value": 24}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(platform), base_url="http://p")
    sla = PlatformReviewSla(
        ServiceClient(http, dev_service_signer(), "agents", "platform", ["settings:view"], tenant=current_tenant)
    )
    with tenant_scope("acme"):
        hours = await sla.hours()
        assert await sla.hours() == hours, "a second read within the minute is cached"
    assert hours == 24 and reads == ["/v1/policies/reviewSlaHours"]
    now = datetime.now(UTC)
    req: dict[str, Any] = {
        "id": "AGP-1",
        "kind": "agent",
        "version": 2,
        "subject_id": "ag_x",
        "requested_by": "james@northfield.example",
        "note": "",
        "body": {},
        "status": "pending",
        "created_at": now.isoformat(),
        "decided_by": None,
        "decided_at": None,
    }
    assert review_view(req, name="X", slug="x", sla_hours=hours, now=now)["slaMinutes"] == 24 * 60
