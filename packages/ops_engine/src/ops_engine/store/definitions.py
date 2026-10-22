"""Stored v2 definitions: one row per version, immutable once written except for its stage (draft, live, paused,
superseded), which only the transitions below change."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store import Guarantee

from .tables import engine_definitions, engine_runs, engine_steps
from .tx import LIVE_WORKFLOWS, Transactions


class WorkflowOwnedError(PermissionError):
    """The workflow id belongs to another team; a team cannot publish a version over it."""


# The stages that serve the workflow: at most one version is in one of them.
CURRENT = ("live", "paused")
# The node type whose step opens a Human Task (node_types.py, executor review.open: the only effects="human" type).
HUMAN_REVIEW = "ops.flow.humanReview"


def _seen_by(team: str | None) -> sa.ColumnElement[bool]:
    """Rows `team` may see: its own and the unowned ones; every row when no team is selected (the loops, dev)."""
    t = engine_definitions
    return sa.true() if team is None else sa.or_(t.c.team_id == team, t.c.team_id.is_(None))


class DefinitionStore:
    # A version is the next number for its workflow unless its digest is stored already (CAS on the unique digest).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, tx: Transactions) -> None:
        self.tx = tx

    async def publish(
        self,
        workflow_id: str,
        *,
        name: str,
        definition: dict[str, Any],
        digest: str,
        now: str,
        by: str,
        team: str | None = None,
        stage: str = "draft",
    ) -> tuple[int, bool]:
        """Stores the next version at `stage` (a save is a draft; only the dev seed stores one live, through
        `go_live`); the same definition again returns its version. Returns (version, created)."""
        t = engine_definitions
        async with self.tx.tenant_tx() as c:
            # The id's existing versions, locked: a workflow id belongs to the team that first published it.
            rows = (
                await c.execute(sa.select(t.c.team_id).where(t.c.workflow_id == workflow_id).with_for_update())
            ).all()
            owners = {r.team_id for r in rows}
            if owners and owners != {team} and not (team is None and owners == {None}):
                raise WorkflowOwnedError(f"workflow id {workflow_id} belongs to another team")
            same = (
                await c.execute(sa.select(t.c.version).where(t.c.workflow_id == workflow_id, t.c.digest == digest))
            ).first()
            if same is not None:
                return int(same.version), False
            latest = (
                await c.execute(sa.select(sa.func.max(t.c.version)).where(t.c.workflow_id == workflow_id))
            ).scalar()
            version = int(latest or 0) + 1
            await c.execute(
                t.insert().values(
                    tenant_id=self.tx.tenant(),
                    workflow_id=workflow_id,
                    version=version,
                    digest=digest,
                    name=name,
                    definition=definition,
                    created_at=now,
                    created_by=by,
                    team_id=team,
                    stage=stage,
                )
            )
            return version, True

    async def current(self, workflow_id: str, *, team: str | None = None) -> dict[str, Any] | None:
        """The version that serves the workflow, live or paused; None when no version has been approved."""
        t = engine_definitions
        q = t.select().where(
            t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant(), t.c.stage.in_(CURRENT), _seen_by(team)
        )
        async with self.tx.tenant_tx() as c:
            row = (await c.execute(q.order_by(t.c.version.desc()).limit(1))).mappings().first()
        return dict(row) if row else None

    async def currents(self, workflow_ids: set[str]) -> dict[str, dict[str, Any]]:
        """current() for each of these workflows in one query, so a list of many runs reads the versions that serve
        their workflows together; a workflow with no approved version is left out."""
        if not workflow_ids:
            return {}
        t = engine_definitions
        q = t.select().where(
            t.c.workflow_id.in_(sorted(workflow_ids)), t.c.tenant_id == self.tx.tenant(), t.c.stage.in_(CURRENT)
        )
        async with self.tx.tenant_tx() as c:
            rows = (await c.execute(q.order_by(t.c.version))).mappings().all()
        # Ascending, so each workflow keeps its highest version, as current() orders and takes the first.
        return {str(r["workflow_id"]): dict(r) for r in rows}

    async def live(self, workflow_id: str, *, team: str | None = None) -> dict[str, Any] | None:
        """The version a live run starts on; None when there is none or the workflow is paused."""
        row = await self.current(workflow_id, team=team)
        return row if row and row["stage"] == "live" else None

    async def live_everywhere(self) -> list[dict[str, Any]]:
        """Every live version in every tenant, for a loop that serves live workflows from outside any request (the
        mailbox listener). Paused versions are left out: they start no runs."""
        t = engine_definitions
        async with self.tx.system_tx(LIVE_WORKFLOWS) as c:
            live = sa.and_(t.c.stage == "live", t.c.archived_at.is_(None))
            rows = await c.execute(t.select().where(live).order_by(t.c.tenant_id, t.c.workflow_id))
            return [dict(r) for r in rows.mappings()]

    async def go_live(self, workflow_id: str, version: int) -> str:
        """Makes `version` the one that serves the workflow and supersedes the one before, in one transaction. A
        paused workflow stays paused on the new version. Returns the version's stage; LookupError when it is gone."""
        t = engine_definitions
        tenant = self.tx.tenant()
        mine = sa.and_(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id)
        async with self.tx.tenant_tx() as c:
            rows = (await c.execute(sa.select(t.c.version, t.c.stage).where(mine).with_for_update())).all()
            if version not in {r.version for r in rows}:
                raise LookupError(f"{workflow_id} version {version} no longer exists")
            stage = "paused" if any(r.stage == "paused" for r in rows) else "live"
            others = sa.and_(mine, t.c.version != version, t.c.stage.in_(CURRENT))
            await c.execute(t.update().where(others).values(stage="superseded"))
            await c.execute(t.update().where(mine, t.c.version == version).values(stage=stage))
        return stage

    async def set_paused(self, workflow_id: str, paused: bool, *, team: str | None = None) -> dict[str, Any] | None:
        """Pauses or resumes the version that serves the workflow; None when it has none. Runs in flight keep going:
        only new live starts are refused."""
        t = engine_definitions
        where = sa.and_(
            t.c.tenant_id == self.tx.tenant(), t.c.workflow_id == workflow_id, t.c.stage.in_(CURRENT), _seen_by(team)
        )
        async with self.tx.tenant_tx() as c:
            await c.execute(t.update().where(where).values(stage="paused" if paused else "live"))
        return await self.current(workflow_id, team=team)

    async def set_archived(
        self, workflow_id: str, archived: bool, *, by: str, now: str, team: str | None = None
    ) -> dict[str, Any] | None:
        """Archives every version of the workflow, or restores it (c-274); its stages, versions and runs are kept, so
        a restored workflow serves as it did. Runs already started keep going. None when `team` sees no version."""
        t = engine_definitions
        where = sa.and_(t.c.tenant_id == self.tx.tenant(), t.c.workflow_id == workflow_id, _seen_by(team))
        values = {"archived_at": now, "archived_by": by} if archived else {"archived_at": None, "archived_by": None}
        async with self.tx.tenant_tx() as c:
            await c.execute(t.update().where(where).values(**values))
        return await self.get(workflow_id, team=team)

    async def get(
        self, workflow_id: str, version: int | None = None, *, team: str | None = None
    ) -> dict[str, Any] | None:
        """One version, the latest when `version` is None; None when `team` may not see it."""
        t = engine_definitions
        q = t.select().where(t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant(), _seen_by(team))
        q = q.where(t.c.version == version) if version is not None else q.order_by(t.c.version.desc()).limit(1)
        async with self.tx.tenant_tx() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def pinned(self, keys: set[tuple[str, int]]) -> dict[tuple[str, int], dict[str, Any]]:
        """The versions at these (workflow_id, version) pairs in one query, so a page naming the workflows of many runs
        reads them together; a pair with no row is left out."""
        if not keys:
            return {}
        t = engine_definitions
        # An OR of pairs, not a tuple IN, which SQL Server refuses.
        pairs = sa.or_(*(sa.and_(t.c.workflow_id == w, t.c.version == v) for w, v in sorted(keys)))
        async with self.tx.tenant_tx() as c:
            rows = (await c.execute(t.select().where(t.c.tenant_id == self.tx.tenant(), pairs))).mappings().all()
        return {(str(r["workflow_id"]), int(r["version"])): dict(r) for r in rows}

    async def versions(self, workflow_id: str) -> list[dict[str, Any]]:
        t = engine_definitions
        q = (
            sa.select(t.c.version, t.c.digest, t.c.created_at, t.c.created_by, t.c.stage)
            .where(t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant())
            .order_by(t.c.version)
        )
        async with self.tx.tenant_tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def summaries(self, since: str | None = None, *, team: str | None = None) -> list[dict[str, Any]]:
        """Each workflow's latest version (name, version, digest, definition, stage, when and by whom), the version
        that serves it with its stage (`current_version`, `current_stage`; None before the first approval), how many
        runs it has had on any version, and how many started at or after `since` (an ISO time; none when left out),
        how many of those opened a Human Task (`reviewed`), and how many Human Tasks are open now (`open_reviews`);
        the caller filters, sorts and pages."""
        t, r = engine_definitions, engine_runs
        tenant = self.tx.tenant()
        latest = (
            sa.select(t.c.workflow_id, sa.func.max(t.c.version).label("version"))
            .where(t.c.tenant_id == tenant, _seen_by(team))
            .group_by(t.c.workflow_id)
            .subquery()
        )
        # At most one version is live or paused, so max() of its stage is that stage.
        serving = (
            sa.select(
                t.c.workflow_id,
                sa.func.max(t.c.version).label("current_version"),
                sa.func.max(t.c.stage).label("current_stage"),
            )
            .where(t.c.tenant_id == tenant, t.c.stage.in_(CURRENT))
            .group_by(t.c.workflow_id)
            .subquery()
        )
        recent = sa.case((r.c.created_at >= since, 1), else_=0) if since else sa.literal(0)
        runs = (
            sa.select(r.c.workflow_id, sa.func.count().label("runs"), sa.func.sum(recent).label("recent"))
            .where(r.c.tenant_id == tenant)
            .group_by(r.c.workflow_id)
            .subquery()
        )
        # A Human Task is a journaled step of the Human review node type; a step that failed to open one has status
        # "error". A task is open while its step waits and its run still does (a cancelled run keeps its row).
        s = engine_steps
        reached = sa.case((r.c.created_at >= since, r.c.id)) if since else sa.null()
        is_open = sa.and_(s.c.status == "waiting", r.c.status == "waiting")
        humans = (
            sa.select(
                r.c.workflow_id,
                sa.func.count(sa.distinct(reached)).label("reviewed"),
                sa.func.sum(sa.case((is_open, 1), else_=0)).label("open_reviews"),
            )
            .join(s, sa.and_(s.c.run_id == r.c.id, s.c.tenant_id == r.c.tenant_id))
            .where(r.c.tenant_id == tenant, s.c.node_type == HUMAN_REVIEW, s.c.status != "error")
            .group_by(r.c.workflow_id)
            .subquery()
        )
        q = (
            sa.select(
                t.c.workflow_id,
                t.c.name,
                t.c.version,
                t.c.digest,
                t.c.definition,
                t.c.created_at,
                t.c.created_by,
                t.c.team_id,
                t.c.stage,
                t.c.archived_at,
                serving.c.current_version,
                serving.c.current_stage,
                runs.c.runs,
                runs.c.recent,
                humans.c.reviewed,
                humans.c.open_reviews,
            )
            .join(latest, sa.and_(t.c.workflow_id == latest.c.workflow_id, t.c.version == latest.c.version))
            .outerjoin(serving, serving.c.workflow_id == t.c.workflow_id)
            .outerjoin(runs, runs.c.workflow_id == t.c.workflow_id)
            .outerjoin(humans, humans.c.workflow_id == t.c.workflow_id)
            .where(t.c.tenant_id == tenant, _seen_by(team))
        )
        async with self.tx.tenant_tx() as c:
            rows = (await c.execute(q)).mappings()
            return [
                dict(row)
                | {
                    "runs": int(row["runs"] or 0),
                    "recent": int(row["recent"] or 0),
                    "reviewed": int(row["reviewed"] or 0),
                    "open_reviews": int(row["open_reviews"] or 0),
                }
                for row in rows
            ]

    async def delete_draft(self, workflow_id: str, *, team: str | None = None) -> str:
        """Removes every version of a workflow that has never run. The versions are locked first, and a run start
        locks the version it pins (RunStore.create), so a start either commits before this reads the runs (and the
        workflow is kept) or finds its version gone. Returns "deleted", "missing" or "has_runs"."""
        t, r = engine_definitions, engine_runs
        tenant = self.tx.tenant()
        async with self.tx.tenant_tx() as c:
            locked = await c.execute(
                sa.select(t.c.version)
                .where(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id, _seen_by(team))
                .with_for_update()
            )
            if locked.first() is None:
                return "missing"  # none, or another team's
            runs = (
                await c.execute(
                    sa.select(sa.func.count()).where(r.c.tenant_id == tenant, r.c.workflow_id == workflow_id)
                )
            ).scalar()
            if runs:
                return "has_runs"
            res = await c.execute(t.delete().where(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id))
            return "deleted" if res.rowcount else "missing"
