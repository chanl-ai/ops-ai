"""Cases (c-128): a long-lived issue a team works over days or weeks, and its timeline. A case has a status, an
assignee, a priority, an optional customer (the bank's id and name; ops-ai keeps no customer list), and two deadlines,
response and resolution, both paused while the case waits on the customer. Producers (a workflow step, an agent, a
person) open a case with a key of their own, so a retry finds the case it opened; runs, chats, decisions, notes and
field changes are timeline events. Every row carries tenant and team; a reader sees only the teams it names."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import current_tenant, tenant_tx

Status = Literal["open", "waiting_on_customer", "waiting_on_us", "resolved", "closed"]
Priority = Literal["low", "normal", "high", "urgent"]
EventKind = Literal["opened", "run", "chat", "decision", "note", "field", "link"]
STATUSES: tuple[Status, ...] = ("open", "waiting_on_customer", "waiting_on_us", "resolved", "closed")
PRIORITIES: tuple[Priority, ...] = ("low", "normal", "high", "urgent")
# The deadlines a case starts with when its producer names none: (first response, resolution), by priority. A team
# setting replaces them later; today they are the product's.
DEFAULT_DEADLINES: dict[Priority, tuple[timedelta, timedelta]] = {
    "urgent": (timedelta(hours=1), timedelta(hours=8)),
    "high": (timedelta(hours=4), timedelta(days=1)),
    "normal": (timedelta(hours=8), timedelta(days=3)),
    "low": (timedelta(days=1), timedelta(days=7)),
}
PAUSED = "waiting_on_customer"

cases = sa.Table(
    "cases",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    # The producer's own key (a run's or chat's), unique in the team: opening the case again finds it.
    sa.Column("producer_key", sa.String(200)),
    sa.Column("subject", sa.String(300), nullable=False),
    sa.Column("customer_id", sa.String(200)),
    sa.Column("customer_name", sa.String(300)),
    sa.Column("status", sa.String(32), nullable=False),
    sa.Column("assignee", sa.String(320)),
    sa.Column("priority", sa.String(16), nullable=False),
    sa.Column("response_due_at", sa.String(32), nullable=False),
    sa.Column("resolution_due_at", sa.String(32), nullable=False),
    sa.Column("responded_at", sa.String(32)),
    # Set while the case waits on the customer; leaving that status moves both deadlines on by the pause.
    sa.Column("paused_since", sa.String(32)),
    # What the producer read or worked out about the issue, by name (an Open or Add to case step's fields).
    sa.Column("fields", sa.JSON),
    # The case type and published version the case was opened with (c-291); None when none was named.
    sa.Column("type_id", sa.String(64)),
    sa.Column("type_version", sa.Integer),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    sa.UniqueConstraint("tenant_id", "team_id", "producer_key", name="uq_cases_producer_key"),
    sa.Index("ix_cases_team_due", "tenant_id", "team_id", "resolution_due_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

case_events = sa.Table(
    "case_events",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, index=True),
    sa.Column("case_id", sa.String(64), nullable=False, index=True),
    sa.Column("kind", sa.String(16), nullable=False),
    # The record the event is about (a run, chat thread, review, or the linked case), when there is one.
    sa.Column("ref", sa.String(200)),
    sa.Column("detail", sa.Text, nullable=False),
    sa.Column("by", sa.String(320), nullable=False),
    sa.Column("at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


class CaseNotFound(LookupError):
    """No case with that id in the teams the reader names."""


@dataclass(frozen=True)
class Opened:
    case: dict[str, Any]
    # False when the producer key found the case a retry had already opened.
    created: bool


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _row(r: Any) -> dict[str, Any]:
    return dict(r._mapping)  # pyright: ignore[reportPrivateUsage]


class CaseStore:
    # A field change and its timeline event commit together; the producer key's unique index makes an open idempotent.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def open(
        self,
        *,
        team_id: str,
        subject: str,
        priority: Priority,
        by: str,
        producer_key: str | None = None,
        customer_id: str | None = None,
        customer_name: str | None = None,
        assignee: str | None = None,
        response_due_at: str | None = None,
        resolution_due_at: str | None = None,
        fields: dict[str, Any] | None = None,
        type_id: str | None = None,
        type_version: int | None = None,
        now: datetime | None = None,
    ) -> Opened:
        at = now or datetime.now(UTC)
        response, resolution = DEFAULT_DEADLINES[priority]
        values = {
            "id": new_id("case"),
            "team_id": team_id,
            "producer_key": producer_key,
            "subject": subject,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "status": "open",
            "assignee": assignee,
            "priority": priority,
            "response_due_at": response_due_at or _iso(at + response),
            "resolution_due_at": resolution_due_at or _iso(at + resolution),
            "created_by": by,
            "created_at": _iso(at),
            "updated_at": _iso(at),
            "fields": fields or None,
            "type_id": type_id,
            "type_version": type_version,
        }
        try:
            async with tenant_tx(self.engine) as c:
                await c.execute(cases.insert().values(**values))
                await _event(c, str(values["id"]), "opened", ref=None, detail={"subject": subject}, by=by, at=_iso(at))
        except IntegrityError:
            if producer_key is None:
                raise
            async with tenant_tx(self.engine) as c:
                q = sa.select(cases).where(
                    cases.c.team_id == team_id, cases.c.producer_key == producer_key, team_visible(cases)
                )
                return Opened(_row((await c.execute(q)).one()), created=False)
        return Opened(await self.get(str(values["id"]), [team_id]), created=True)

    async def get(self, case_id: str, teams: list[str]) -> dict[str, Any]:
        """The case if it is in `teams`."""
        async with tenant_tx(self.engine) as c:
            q = sa.select(cases).where(cases.c.id == case_id, cases.c.team_id.in_(teams), team_visible(cases))
            row = (await c.execute(q)).first()
        if row is None:
            raise CaseNotFound(case_id)
        return _row(row)

    async def list(
        self,
        teams: list[str],
        *,
        status: list[str] | None = None,
        assignee: str | None = None,
        priority: list[str] | None = None,
        customer_id: str | None = None,
        overdue: bool = False,
        search: str | None = None,
        now: datetime | None = None,
        page: int = 1,
        size: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of the teams' cases, the soonest resolution deadline first, and the count that matched. `search`
        finds the words in the subject, the customer's name or the customer's id, ignoring case."""
        at = _iso(now or datetime.now(UTC))
        where: list[Any] = [cases.c.team_id.in_(teams), team_visible(cases)]
        if status:
            where.append(cases.c.status.in_(status))
        if assignee:
            where.append(cases.c.assignee == assignee)
        if priority:
            where.append(cases.c.priority.in_(priority))
        if customer_id:
            where.append(cases.c.customer_id == customer_id)
        if search and search.strip():
            like = f"%{search.strip()}%"
            where.append(
                sa.or_(cases.c.subject.ilike(like), cases.c.customer_name.ilike(like), cases.c.customer_id.ilike(like))
            )
        if overdue:
            # A paused case is not overdue while it waits on the customer.
            where.append(
                sa.and_(
                    cases.c.paused_since.is_(None),
                    cases.c.status.not_in(("resolved", "closed")),
                    cases.c.resolution_due_at < at,
                )
            )
        async with tenant_tx(self.engine) as c:
            total = int((await c.execute(sa.select(sa.func.count()).select_from(cases).where(*where))).scalar_one())
            q = (
                sa.select(cases)
                .where(*where)
                .order_by(cases.c.resolution_due_at, cases.c.id)
                .limit(size)
                .offset((page - 1) * size)
            )
            rows = [_row(r) for r in (await c.execute(q)).all()]
        return rows, total

    async def events(self, case_id: str) -> list[dict[str, Any]]:
        async with tenant_tx(self.engine) as c:
            q = (
                sa.select(case_events)
                .where(case_events.c.case_id == case_id)
                .order_by(case_events.c.at, case_events.c.id)
            )
            rows = (await c.execute(q)).all()
        return [{**_row(r), "detail": json.loads(r.detail)} for r in rows]

    async def events_by_id(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """These timeline events by id in one query, each with its detail (the Activity page words its case rows)."""
        if not ids:
            return {}
        async with tenant_tx(self.engine) as c:
            rows = (await c.execute(sa.select(case_events).where(case_events.c.id.in_(ids)))).all()
        return {str(r.id): {**_row(r), "detail": json.loads(r.detail)} for r in rows}

    async def merge_fields(self, case_id: str, fields: dict[str, Any]) -> None:
        """Adds `fields` to the case's own, a name given again taking the new value."""
        async with tenant_tx(self.engine) as c:
            q = sa.select(cases.c.fields).where(cases.c.id == case_id, team_visible(cases)).with_for_update()
            held = cast(dict[str, Any] | None, (await c.execute(q)).scalar()) or {}
            await c.execute(
                cases.update()
                .where(cases.c.id == case_id)
                .values(fields=held | fields, updated_at=_iso(datetime.now(UTC)))
            )

    async def add_event(
        self, case_id: str, kind: EventKind, *, ref: str | None, detail: dict[str, Any], by: str
    ) -> None:
        async with tenant_tx(self.engine) as c:
            await _event(c, case_id, kind, ref=ref, detail=detail, by=by, at=now_iso())
            await c.execute(cases.update().where(cases.c.id == case_id).values(updated_at=now_iso()))

    async def change(
        self, case_id: str, changes: dict[str, Any], *, by: str, now: datetime | None = None
    ) -> dict[str, Any]:
        """Applies field changes, one `field` event each, in one transaction. Entering `waiting_on_customer` pauses both
        deadlines; leaving it moves both on by the pause. Returns the case as it is now."""
        at = now or datetime.now(UTC)
        async with tenant_tx(self.engine) as c:
            row = (
                await c.execute(sa.select(cases).where(cases.c.id == case_id, team_visible(cases)).with_for_update())
            ).first()
            if row is None:
                raise CaseNotFound(case_id)
            before = _row(row)
            values: dict[str, Any] = {}
            for field, value in changes.items():
                if before.get(field) != value:
                    values[field] = value
            status = values.get("status")
            if status == PAUSED and before["paused_since"] is None:
                values["paused_since"] = _iso(at)
            elif status is not None and status != PAUSED and before["paused_since"] is not None:
                paused = at - _parse(str(before["paused_since"]))
                values["paused_since"] = None
                for due in ("response_due_at", "resolution_due_at"):
                    if due not in values:
                        values[due] = _iso(_parse(str(before[due])) + paused)
            if not values:
                return before
            values["updated_at"] = _iso(at)
            await c.execute(cases.update().where(cases.c.id == case_id).values(**values))
            # An explicit responded_at in the same change lands first, so the field events below keep it.
            for field in sorted(changes, key=lambda f: f != "responded_at"):
                if field in values:
                    detail = {"field": field, "before": before.get(field), "after": values[field]}
                    await _event(c, case_id, "field", ref=None, detail=detail, by=by, at=_iso(at))
            after = _row((await c.execute(sa.select(cases).where(cases.c.id == case_id, team_visible(cases)))).one())
        return after

    async def counts(self, teams: list[str], *, now: datetime | None = None) -> dict[str, int]:
        """What waits on the teams (c-129): cases a person has to act on (open or waiting on us) and cases past their
        resolution deadline (not paused, not resolved). One query."""
        at = _iso(now or datetime.now(UTC))
        needs = cases.c.status.in_(("open", "waiting_on_us"))
        breaching = sa.and_(
            cases.c.paused_since.is_(None),
            cases.c.status.not_in(("resolved", "closed")),
            cases.c.resolution_due_at < at,
        )
        q = (
            sa.select(
                sa.func.count().filter(needs).label("needs"), sa.func.count().filter(breaching).label("breaching")
            )
            .select_from(cases)
            .where(cases.c.team_id.in_(teams), team_visible(cases))
        )
        async with tenant_tx(self.engine) as c:
            row = (await c.execute(q)).one()
        return {"needs": int(row.needs or 0), "breaching": int(row.breaching or 0)}

    async def cases_of_runs(self, run_ids: list[str]) -> dict[str, str]:
        """The case each run is on, by run id, from the `run` entries of the timelines; a run added to two cases
        answers the later one. One query for a whole list of reviews."""
        if not run_ids:
            return {}
        async with tenant_tx(self.engine) as c:
            q = (
                sa.select(case_events.c.ref, case_events.c.case_id)
                .where(case_events.c.kind == "run", case_events.c.ref.in_(run_ids))
                .order_by(case_events.c.at, case_events.c.id)
            )
            return {str(r.ref): str(r.case_id) for r in (await c.execute(q)).all()}

    async def subjects(self, case_ids: list[str]) -> dict[str, str]:
        """Each case's subject by id, for any team, in one query; a case not found is left out."""
        if not case_ids:
            return {}
        async with tenant_tx(self.engine) as c:
            q = sa.select(cases.c.id, cases.c.subject).where(
                team_visible(cases), cases.c.tenant_id == current_tenant(), cases.c.id.in_(case_ids)
            )
            rows = (await c.execute(q)).all()
        return {str(r.id): str(r.subject) for r in rows}

    async def summaries(self, case_ids: list[str], teams: list[str]) -> dict[str, dict[str, Any]]:
        """Each case's subject, customer name and fields by id, for the cases of `teams` only, in one query: a run's
        page names the cases its child runs opened that its reader may open (c-477). A case of another team, or not
        found, is left out."""
        if not case_ids or not teams:
            return {}
        async with tenant_tx(self.engine) as c:
            q = sa.select(cases.c.id, cases.c.subject, cases.c.customer_name, cases.c.fields).where(
                team_visible(cases),
                cases.c.tenant_id == current_tenant(),
                cases.c.id.in_(case_ids),
                cases.c.team_id.in_(teams),
            )
            rows = (await c.execute(q)).all()
        return {
            str(r.id): {"subject": str(r.subject), "customer": r.customer_name, "fields": dict(r.fields or {})}
            for r in rows
        }

    async def link(self, case_id: str, other_id: str, *, by: str) -> None:
        """Two cases about one issue: a `link` event on each, naming the other. Linking twice adds nothing."""
        at = now_iso()
        async with tenant_tx(self.engine) as c:
            for a, b in ((case_id, other_id), (other_id, case_id)):
                q = sa.select(case_events.c.id).where(
                    case_events.c.case_id == a, case_events.c.kind == "link", case_events.c.ref == b
                )
                if (await c.execute(q)).first() is None:
                    await _event(c, a, "link", ref=b, detail={"case": b}, by=by, at=at)


# What counts as working the case for its first response (c-508): a person's note, decision, or change of one of these.
_RESPONSE_FIELDS = frozenset({"status", "assignee", "priority"})
# Who is not a person, as api/actors.py parses them: runs, agents, API keys, events and triggers.
_AUTOMATED = ("run:", "agent:", "key:", "event:", "trigger:")


def _starts_response(kind: str, by: str, detail: dict[str, Any]) -> bool:
    if not by or by.startswith(_AUTOMATED):
        return False
    return kind in ("note", "decision") or (kind == "field" and detail.get("field") in _RESPONSE_FIELDS)


async def _event(
    c: AsyncConnection, case_id: str, kind: str, *, ref: str | None, detail: dict[str, Any], by: str, at: str
) -> None:
    if _starts_response(kind, by, detail):
        # Set once: the first person's work on the case is its first response; a responded_at already set (an import's
        # explicit value, or an earlier response) is kept.
        await c.execute(
            cases.update().where(cases.c.id == case_id, cases.c.responded_at.is_(None)).values(responded_at=at)
        )
    await c.execute(
        case_events.insert().values(
            # Sorts by when it was written, so events of one transaction (one `at`) keep their order on the timeline.
            id=f"cev_{time.time_ns():020d}_{new_id('x')[-6:]}",
            case_id=case_id,
            kind=kind,
            ref=ref,
            detail=json.dumps(detail),
            by=by,
            at=at,
        )
    )
