"""The rows the Reviews list reads from two of its sources, at most `cap` each: open ones first, then newest, then by
key, so the rows kept at the cap are always the same ones and an open review is the last to be left off. The list
merges these with the waiting workflow runs in Python before it pages (api/hitl_facade.list_reviews), so each source
is bounded here rather than by the page."""

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
        """The acting team's graph threads, at most `cap`: those still running or waiting first, so chats and ended
        threads never push an open review off the list, then most recently changed. Answered most recently changed
        first, the order the list keeps."""
        t = graph_threads
        ended = sa.case((t.c.status == "idle", 1), else_=0)
        q = (
            sa.select(*(t.c[name] for name in ThreadRow.model_fields))
            .where(mine(t), team_visible(t))
            .order_by(ended, t.c.updated_at.desc(), t.c.id.desc())
            .limit(cap)
        )
        async with self.tx() as c:
            found = capped("threads", await rows(c, q, ThreadRow), cap)
        return sorted(found, key=lambda r: (r.updated_at, r.id), reverse=True)

    async def publish_requests(self, cap: int) -> list[PublishRequestRow]:
        """The tenant's publish requests, at most `cap`: pending ones first, so decided history never pushes an open
        request off the list, then newest. The caller keeps the acting team's. Answered newest first."""
        p = publish_requests
        decided = sa.case((p.c.status == "pending", 0), else_=1)
        q = (
            sa.select(*(p.c[name] for name in PublishRequestRow.model_fields))
            .where(p.c.tenant_id == current_tenant())
            .order_by(decided, p.c.created_at.desc(), p.c.id.desc())
            .limit(cap)
        )
        async with self.tx() as c:
            found = capped("publish_requests", await rows(c, q, PublishRequestRow), cap)
        return sorted(found, key=lambda r: (r.created_at, r.id), reverse=True)
