"""Reviews tools-service holds reach where they are decided at start-up (c-163, c-222, c-257), by failure mode: a
seeded waiting review that Human Tasks never shows, one opened with a token for another team or without the scope the
route asks, a version that keeps the seed's id once Reviews named its own, a review Reviews already holds failing the
start-up, and a workflow's open tool access request left on the module (c-166). Reviews is a fake HTTP endpoint here;
who may open a review is agents-service's tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_identity import ServiceClient
from ops_tools.modules.review_handoff import hand_over
from ops_tools.modules.seed import load
from ops_tools.store.modules import ModuleStore, service_outbox
from ops_tools.store.review_handoffs import ReviewHandoffs

from .service_clients import claims, fake_service


def _reviews(*, open_already: bool = False) -> tuple[ServiceClient, list[dict[str, Any]]]:
    """agents-service's POST /v1/publish-requests: records each body with its token's tenant, team and scopes, and
    names the request it opened, or answers that one is already open."""
    got: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/publish-requests"
        c = claims(request)
        got.append(
            {"token": f"{c['tenant_id']}:{c['team_id']}", "scopes": c.get("scopes"), **json.loads(request.content)}
        )
        if open_already:
            error = {"code": "review_open", "message": "already open", "status": 409}
            return httpx.Response(409, json={"success": False, "error": error})
        return httpx.Response(201, json={"success": True, "data": {"id": f"TMR-{1000 + len(got)}"}})

    return fake_service(handler, "agents", ["tools:publish"]), got


async def test_a_seeded_waiting_review_is_opened_for_its_modules_team_on_its_publishers_behalf(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    client, got = _reviews()
    await hand_over(ReviewHandoffs(engine), client)
    mine = [g for g in got if g["token"].startswith(f"{tenant}:")]
    assert mine, "the seed has a module waiting for review"
    module = await ModuleStore(engine).get(tenant, mine[0]["subjectId"])
    assert module is not None
    v = next(x for x in module["versions"] if x["status"] == "in_review")
    assert mine[0]["token"] == f"{tenant}:{module['team_id']}" and mine[0]["scopes"] == ["tools:publish"], mine[0]
    assert (mine[0]["kind"], mine[0]["requestedBy"]) == ("tool_module", v["published_by"]), mine[0]
    assert v["review_id"].startswith("TMR-"), "the version takes the id Reviews named"
    again = len(got)
    await hand_over(ReviewHandoffs(engine), client)
    assert len([g for g in got[again:] if g["token"].startswith(f"{tenant}:")]) == 0, "an opened review is not reopened"


async def test_a_review_reviews_already_holds_is_skipped_and_keeps_the_seeds_id(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    client, got = _reviews(open_already=True)
    await hand_over(ReviewHandoffs(engine), client)
    mine = [g for g in got if g["token"].startswith(f"{tenant}:")]
    module = await ModuleStore(engine).get(tenant, mine[0]["subjectId"])
    assert module is not None
    v = next(x for x in module["versions"] if x["status"] == "in_review")
    assert v["review_id"].startswith("TMP-"), v


async def test_an_open_access_request_is_handed_to_its_workflow_once_for_its_modules_team(
    engine: AsyncEngine, seed: dict[str, Any], tenant: str, catalog_tools: list[dict[str, Any]]
) -> None:
    # c-257: an open request becomes its system workflow's event, with the run key written in the same transaction,
    # so a second hand-over finds nothing to report.
    await load(ModuleStore(engine), seed, tenant_id=tenant, now=datetime.now(UTC), catalog=catalog_tools)
    client, _ = _reviews()
    await hand_over(ReviewHandoffs(engine), client)
    async with engine.connect() as c:
        q = sa.select(service_outbox).where(service_outbox.c.tenant_id == tenant)
        events = [dict(r) for r in (await c.execute(q)).mappings()]
    assert events, "the seed has a workflow request waiting on a module"
    module = await ModuleStore(engine).get(tenant, str(events[0]["payload"]["moduleId"]))
    assert module is not None
    a = next(x for x in module["approvals"] if x["id"] == events[0]["event_key"])
    assert (events[0]["name"], events[0]["team_id"]) == ("tool_access.requested", module["team_id"])
    assert (a["status"], a["review_id"]) == ("requested", f"tool_access.requested:{a['id']}")
    await hand_over(ReviewHandoffs(engine), client)
    async with engine.connect() as c:
        again = (
            await c.execute(
                sa.select(sa.func.count()).select_from(service_outbox).where(service_outbox.c.tenant_id == tenant)
            )
        ).scalar()
    assert again == len(events), "a request handed over is not sent twice"
