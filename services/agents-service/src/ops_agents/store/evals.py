"""Saved eval cases and the runs of them, for agents and skills: one row per case in the asset's team, and one row
per run, kept so a run can be repeated and compared. A case set is replaced whole by the person who saves it; a run
is only ever added. A workflow's test runs are `registry_validations` and are read beside these, never copied."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Json
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

eval_cases = sa.Table(
    "eval_cases",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("asset_id", sa.String(64), nullable=False),
    sa.Column("position", sa.Integer, nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    # active cases are run; a draft (proposed from a review) waits for its owner.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("source", sa.String(16), nullable=False),
    sa.Column("review_id", sa.String(64)),
    sa.Column("reason", sa.Text, nullable=False, default=""),
    # The case as the person wrote it: input, context and checks.
    sa.Column("body", sa.JSON, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    sa.Index("ix_eval_cases_asset", "tenant_id", "team_id", "kind", "asset_id"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

eval_runs = sa.Table(
    "eval_runs",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("asset_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("live_version", sa.Integer),
    sa.Column("trigger", sa.String(24), nullable=False),
    sa.Column("passed", sa.Integer, nullable=False),
    sa.Column("total", sa.Integer, nullable=False),
    sa.Column("live_passed", sa.Integer),
    sa.Column("regressions", sa.Integer, nullable=False),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    sa.Column("cost_usd", sa.Float(), nullable=False, default=0.0),
    sa.Column("results", sa.JSON, nullable=False),
    sa.Column("started_by", sa.String(320), nullable=False),
    sa.Column("ran_at", sa.String(32), nullable=False),
    sa.Index("ix_eval_runs_asset", "tenant_id", "team_id", "kind", "asset_id", "ran_at"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class EvalStore(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION})

    async def replace_cases(self, kind: str, asset_id: str, team_id: str, cases: list[Json], *, by: str) -> None:
        """Makes `cases` the asset's active set in one transaction; its draft cases are left."""
        t = eval_cases
        now = now_iso()
        async with self.tx() as c:
            await c.execute(
                t.delete().where(t.c.kind == kind, t.c.asset_id == asset_id, t.c.status == "active", team_visible(t))
            )
            if cases:
                await c.execute(
                    t.insert(),
                    [
                        {
                            "id": new_id("evc"),
                            "team_id": team_id,
                            "kind": kind,
                            "asset_id": asset_id,
                            "position": i,
                            "name": str(case["name"]),
                            "status": "active",
                            "source": "manual",
                            "reason": "",
                            "body": case,
                            "created_by": by,
                            "created_at": now,
                        }
                        for i, case in enumerate(cases)
                    ],
                )

    async def cases(self, kind: str | None = None, asset_id: str | None = None) -> list[Json]:
        t = eval_cases
        q = sa.select(t).where(team_visible(t)).order_by(t.c.kind, t.c.asset_id, t.c.position)
        if kind:
            q = q.where(t.c.kind == kind)
        if asset_id:
            q = q.where(t.c.asset_id == asset_id)
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def add_run(self, row: Json) -> None:
        async with self.tx() as c:
            await c.execute(eval_runs.insert().values(**row))

    async def runs(self, kind: str | None = None, asset_id: str | None = None) -> list[Json]:
        """The acting team's runs, newest first."""
        t = eval_runs
        q = sa.select(t).where(team_visible(t)).order_by(t.c.ran_at.desc(), t.c.id.desc())
        if kind:
            q = q.where(t.c.kind == kind)
        if asset_id:
            q = q.where(t.c.asset_id == asset_id)
        async with self.tx() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]
