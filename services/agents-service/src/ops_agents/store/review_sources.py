"""The rows the Reviews list reads from two of its sources, at most `cap` each, newest first and then by key, so the
rows kept at the cap are always the same ones. The list merges these with the waiting workflow runs in Python before
it pages (api/hitl_facade.list_reviews), so each source is bounded here rather than by the page."""

from __future__ import annotations

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue

from ops_service_kit.logging import get_logger
from ops_store.rows import rows
from ops_store.team_scope import team_visible

from .agent_registry import publish_requests
from .graphs import graph_threads, mine
from .tenancy import RuntimeStore, current_tenant

log = get_logger(__name__)


class ThreadRow(BaseModel):
    """A `graph_threads` row, every column."""

    id: str
    graph: str
    meta: dict[str, JsonValue]
    team_id: str
    created_at: str
    updated_at: str
    status: str
    version: int | None
    digest: str | None
    external_key: str | None
    deployment_id: str | None
    parent_thread_id: str | None
    overrides: dict[str, JsonValue] | None
    owner: str | None
    tenant_id: str


class PublishRequestRow(BaseModel):
    """A `registry_publish_requests` row, every column."""

    tenant_id: str
    id: str
    kind: str
    subject_id: str
    version: int
    status: str
    note: str
    requested_by: str
    created_at: str
    decided_at: str | None
    decided_by: str | None
    decision_reason: str | None
    body: dict[str, JsonValue]
    team_id: str


def capped[R: BaseModel](source: str, found: list[R], cap: int) -> list[R]:
    """`found`, logging when the source filled its cap, so a list that leaves older rows off is seen."""
    if len(found) >= cap:
        log.warning("review_source_capped", source=source, cap=cap)
    return found


class ReviewSources(RuntimeStore):
    async def threads(self, cap: int) -> list[ThreadRow]:
        """The acting team's graph threads, most recently changed first, at most `cap`."""
        t = graph_threads
        q = sa.select(t).where(mine(t), team_visible(t)).order_by(t.c.updated_at.desc(), t.c.id.desc()).limit(cap)
        async with self.tx() as c:
            return capped("threads", await rows(c, q, ThreadRow), cap)

    async def publish_requests(self, cap: int) -> list[PublishRequestRow]:
        """The tenant's publish requests, newest first, at most `cap`; the caller keeps the acting team's."""
        p = publish_requests
        q = (
            sa.select(p)
            .where(p.c.tenant_id == current_tenant())
            .order_by(p.c.created_at.desc(), p.c.id.desc())
            .limit(cap)
        )
        async with self.tx() as c:
            return capped("publish_requests", await rows(c, q, PublishRequestRow), cap)
