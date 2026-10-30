"""Hosted forms (c-535): a workflow's start form shared as a page of its own, by a signed link that expires or to the
team's signed-in members. One row per form, in the team that shared it; the link's secret is kept only as its hash.

A submission through the link enters the tenant and team its token names and reads the form by id there, so nothing
here reads across teams. The daily cap is counted with the form's row locked, because submissions arrive at once:
`reserve` records the `started` trigger event in the same transaction that counted the day's starts."""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import locked
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx
from .trigger_events import TriggerEvent, trigger_events

Mode = Literal["link", "members"]
MODES: tuple[Mode, ...] = ("link", "members")

form_links = sa.Table(
    "form_links",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("workflow_id", sa.String(200), nullable=False),
    # The path the page is served at, /f/<slug>; unique in the tenant.
    sa.Column("slug", sa.String(80), nullable=False),
    sa.Column("mode", sa.String(16), nullable=False),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("description", sa.String(1000), nullable=False, server_default=""),
    sa.Column("after_text", sa.String(1000), nullable=False, server_default=""),
    # sha256 of the link's secret; a rotated link gets a new secret and the old one stops matching.
    sa.Column("token_hash", sa.String(64), nullable=False),
    sa.Column("expires_at", sa.String(40), nullable=False),
    sa.Column("daily_cap", sa.Integer, nullable=False),
    sa.Column("paused", sa.Boolean, nullable=False, server_default=sa.false()),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("rotated_at", sa.String(32)),
    sa.UniqueConstraint("tenant_id", "slug", name="uq_form_links_slug"),
    sa.Index("ix_form_links_workflow", "tenant_id", "workflow_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


def source_of(form_id: str) -> str:
    """The trigger events of a form's submissions name it as their source, beside a mailbox's `email:<address>`."""
    return f"form:{form_id}"


class FormLinks:
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create(
        self,
        *,
        team_id: str,
        workflow_id: str,
        slug: str,
        mode: Mode,
        daily_cap: int,
        expires_at: str,
        created_by: str,
        title: str = "",
        description: str = "",
        after_text: str = "",
        token_hash: str = "",
    ) -> dict[str, Any]:
        row = {
            "id": new_id("form"),
            "team_id": team_id,
            "workflow_id": workflow_id,
            "slug": slug,
            "mode": mode,
            "title": title or workflow_id,
            "description": description,
            "after_text": after_text,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "daily_cap": daily_cap,
            "created_by": created_by,
            "created_at": now_iso(),
        }
        async with tenant_tx(self.engine) as c:
            await c.execute(form_links.insert().values(**row))
        return {**row, "tenant_id": current_tenant(), "paused": False, "rotated_at": None}

    async def get(self, form_id: str) -> dict[str, Any] | None:
        f = form_links
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(sa.select(f).where(f.c.id == form_id, team_visible(f)))).mappings().first()
        return dict(found) if found is not None else None

    async def by_slug(self, slug: str) -> dict[str, Any] | None:
        """The form at `slug` among the acting team's forms (a members-only page, read as a signed-in person)."""
        f = form_links
        async with tenant_tx(self.engine) as c:
            found = (await c.execute(sa.select(f).where(f.c.slug == slug, team_visible(f)))).mappings().first()
        return dict(found) if found is not None else None

    async def of_workflow(self, workflow_id: str) -> list[dict[str, Any]]:
        f = form_links
        q = sa.select(f).where(f.c.workflow_id == workflow_id, team_visible(f)).order_by(f.c.created_at.desc())
        async with tenant_tx(self.engine) as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def update(self, form_id: str, **values: Any) -> dict[str, Any] | None:
        f = form_links
        async with tenant_tx(self.engine) as c:
            await c.execute(f.update().where(f.c.id == form_id, team_visible(f)).values(**values))
        return await self.get(form_id)

    async def titles(self, form_ids: set[str]) -> dict[str, str]:
        """Each form's title, for naming the runs its link started (`trigger:form:<id>`)."""
        if not form_ids:
            return {}
        f = form_links
        q = sa.select(f.c.id, f.c.title).where(f.c.id.in_(form_ids), team_visible(f))
        async with tenant_tx(self.engine) as c:
            return {str(i): str(t) for i, t in (await c.execute(q)).all()}

    async def reserve(self, form_id: str, *, cap: int, since: str, event: TriggerEvent) -> str | None:
        """Records a `started` submission when the form has started fewer than `cap` runs since `since`, and answers
        its event id; None when the day is full. The form's row stays locked from the count to the insert, so two
        submissions at the last place under the cap cannot both pass."""
        f, t = form_links, trigger_events
        async with tenant_tx(self.engine) as c:
            held = locked(sa.select(f.c.id).where(f.c.id == form_id), f)
            if (await c.execute(held)).first() is None:
                return None
            counted = sa.select(sa.func.count()).where(
                t.c.tenant_id == current_tenant(),
                t.c.source == source_of(form_id),
                t.c.outcome == "started",
                t.c.recorded_at >= since,
            )
            if int((await c.execute(counted)).scalar_one()) >= cap:
                return None
            event_id = new_id("tev")
            await c.execute(
                t.insert().values(
                    id=event_id,
                    team_id=event.team_id,
                    workflow_id=event.workflow_id,
                    source=event.source[:320],
                    event_key=event.event_key,
                    sender=event.sender[:320],
                    subject=event.subject[:500],
                    received_at=event.received_at[:40],
                    outcome="started",
                    run_id=event.run_id,
                    detail=json.dumps(event.detail or {}),
                    recorded_at=now_iso(),
                )
            )
        return event_id

    async def settle(self, event_id: str, *, run_id: str | None, failed: str | None = None) -> None:
        """Names the run a reserved submission started, or turns it into `start_failed`, which the cap does not
        count, when the start raised after the place was taken."""
        t = trigger_events
        values: dict[str, Any] = {"run_id": run_id}
        if failed is not None:
            values |= {"outcome": "start_failed", "detail": json.dumps({"reason": failed})}
        async with tenant_tx(self.engine) as c:
            await c.execute(t.update().where(t.c.id == event_id, team_visible(t)).values(**values))
