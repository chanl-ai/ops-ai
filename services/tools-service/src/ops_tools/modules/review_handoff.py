"""Hands what tools-service holds for review to where it is decided, at start-up (c-163, c-222, c-257). A module
version its seed left waiting for review is opened in agents-service's Reviews through the publish-request route a
person's submit uses, with this service's token scoped to the module's team and naming who published it; Reviews
records that tools-service opened it on their behalf. An open tool access request is reported once as its system
workflow's event."""

from __future__ import annotations

import asyncio

from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger

from ..store.review_handoffs import ReviewHandoffs
from .review_events import access_event

log = get_logger("ops_tools.review_handoff")
# The id the seed gives a version waiting for review until Reviews opens it and names its own.
SEEDED = "TMP-"


async def hand_over(store: ReviewHandoffs, agents: ServiceClient) -> int:
    """Opens each seeded waiting review and reports each open access request; returns how many were handed over.
    Raises when agents-service cannot take a review, leaving the rest for the next run."""
    sent = 0
    modules, waiting = await store.pending()
    for v in waiting:
        m = modules.get((v["tenant_id"], v["module_id"]))
        if m is None or not str(v["review_id"]).startswith(SEEDED):
            continue
        body = {
            "kind": "tool_module",
            "subjectId": v["module_id"],
            "moduleName": m.display_name,
            "moduleVersion": v["version"],
            "requestedBy": v["published_by"] or "the tools-service seed",
        }
        try:
            opened = await agents.post("/v1/publish-requests", body, tenant=v["tenant_id"], team=m.team_id)
        except ServiceCallError as e:
            if e.code != "review_open":
                raise
            # Reviews already holds an open request for the module; the version keeps the seed's id.
            log.info("tool_review_already_open", module=v["module_id"])
            continue
        await store.opened(v, str(opened["id"]))
        sent += 1
    # Open workflow requests for a module's operations run as the tool_access_request system workflow (c-257): each
    # is reported once as its event, for the module's team unless the request already named its deciding team.
    for a in await store.open_access():
        m = modules.get((a["tenant_id"], a["module_id"]))
        if m is None:
            continue
        module = {"id": a["module_id"], "tenant_id": a["tenant_id"], "display_name": m.display_name}
        await store.start_access_run(
            a, event=access_event(module, {**a, "decider_team": a["decider_team"] or m.team_id})
        )
        sent += 1
    return sent


async def keep_handing_over(store: ReviewHandoffs, agents: ServiceClient) -> None:
    """At start-up: tries until agents-service takes the reviews, since the two may start in either order."""
    for attempt in range(60):
        try:
            sent = await hand_over(store, agents)
            log.info("tool_reviews_handed_over", sent=sent)
            return
        except (ServiceCallError, ServiceUnreachable, OSError) as e:
            log.info("tool_reviews_hand_over_waiting", attempt=attempt, error=str(e))
            await asyncio.sleep(5)
