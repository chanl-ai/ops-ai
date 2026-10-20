"""Review decisions (migration 0012) and per-person approvals of a waiting call: the review service's tables until
hitl-service owns them."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .graphs import graph_threads
from .tenancy import current_tenant, tenant_tx

review_decisions = sa.Table(
    "review_decisions",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("decision_id", sa.String(64), primary_key=True),
    sa.Column("decision", sa.String(16), nullable=False),
    sa.Column("reason", sa.Text),
    sa.Column("decided_by", sa.String(200), nullable=False),
    sa.Column("decided_at", sa.String(32), nullable=False),
    sa.Column("review", sa.JSON, nullable=False),
    sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    sa.Column("run_id", sa.String(80)),
    sa.Column("resumed_at", sa.String(32)),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("team_id", sa.String(64)),
    # A fingerprint of the step-up the decision was made under (api/auth.py step_up_ref), never the token.
    sa.Column("step_up_ref", sa.String(40)),
    info=TENANT_SCOPED,
)

review_approvals = sa.Table(
    "review_approvals",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("step", sa.String(200), primary_key=True),
    sa.Column("approver", sa.String(200), primary_key=True),
    sa.Column("input_hash", sa.String(64), nullable=False),
    sa.Column("approved_at", sa.String(32), nullable=False),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("team_id", sa.String(64)),
    info=TENANT_SCOPED,
)


def _team_of(thread_id: str) -> Any:
    return sa.select(graph_threads.c.team_id).where(graph_threads.c.id == thread_id).scalar_subquery()


class ReviewStore:
    # A decision is one insert keyed by its interrupt (a second decision of the same interrupt is refused), and an
    # approval replaces the approver's row and reads the step's approvers in one transaction.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def latest_decisions(self, thread_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
        """The latest decision per thread."""
        q = review_decisions.select().order_by(review_decisions.c.decided_at)
        if thread_ids is not None:
            q = q.where(review_decisions.c.thread_id.in_(thread_ids))
        async with tenant_tx(self.engine) as c:
            return {r["thread_id"]: dict(r) for r in (await c.execute(q)).mappings()}

    async def decisions_of(self, thread_id: str) -> dict[str, dict[str, Any]]:
        """Every decision on the thread, by interrupt id."""
        q = review_decisions.select().where(review_decisions.c.thread_id == thread_id)
        async with tenant_tx(self.engine) as c:
            return {r["decision_id"]: dict(r) for r in (await c.execute(q)).mappings()}

    async def record_decision(
        self,
        thread_id: str,
        decision_id: str,
        *,
        decision: str,
        reason: str | None,
        by: str,
        review: dict[str, Any],
        step_up_ref: str | None = None,
    ) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(
                review_decisions.insert().values(
                    thread_id=thread_id,
                    decision_id=decision_id,
                    decision=decision,
                    reason=reason,
                    decided_by=by,
                    decided_at=now_iso(),
                    review=review,
                    attempts=0,
                    team_id=_team_of(thread_id),
                    step_up_ref=step_up_ref,
                )
            )

    async def update_decision(self, thread_id: str, decision_id: str, **values: Any) -> None:
        keys = (review_decisions.c.thread_id == thread_id, review_decisions.c.decision_id == decision_id)
        async with tenant_tx(self.engine) as c:
            await c.execute(review_decisions.update().where(*keys).values(**values))

    async def approve(
        self, thread_id: str, step: str, approver: str, digest: str, *, distinct: bool
    ) -> list[str] | None:
        """Records `approver`'s approval of the call `step` with input `digest`, replacing any earlier approval of
        theirs on the step, and returns the approvers of this exact input in order. With `distinct`, a second approval
        of the same input by the same person is refused: None, nothing written."""
        mine = (
            review_approvals.c.thread_id == thread_id,
            review_approvals.c.step == step,
            review_approvals.c.approver == approver,
        )
        async with tenant_tx(self.engine) as c:
            if distinct:
                again = await c.execute(
                    sa.select(review_approvals.c.approver).where(*mine, review_approvals.c.input_hash == digest)
                )
                if again.first() is not None:
                    return None
            await c.execute(review_approvals.delete().where(*mine))
            await c.execute(
                review_approvals.insert().values(
                    thread_id=thread_id,
                    step=step,
                    approver=approver,
                    input_hash=digest,
                    approved_at=now_iso(),
                    team_id=_team_of(thread_id),
                )
            )
            rows = await c.execute(
                sa.select(review_approvals.c.approver)
                .where(
                    review_approvals.c.thread_id == thread_id,
                    review_approvals.c.step == step,
                    review_approvals.c.input_hash == digest,
                )
                .order_by(review_approvals.c.approved_at)
            )
            return [str(r[0]) for r in rows]

    async def approvers(self, thread_id: str, step: str) -> list[str]:
        q = (
            sa.select(review_approvals.c.approver)
            .where(review_approvals.c.thread_id == thread_id, review_approvals.c.step == step)
            .order_by(review_approvals.c.approved_at)
        )
        async with tenant_tx(self.engine) as c:
            return [str(r[0]) for r in await c.execute(q)]

    async def approvals_by_step(self, thread_id: str) -> dict[str, list[str]]:
        q = (
            sa.select(review_approvals.c.step, review_approvals.c.approver)
            .where(review_approvals.c.thread_id == thread_id)
            .order_by(review_approvals.c.approved_at)
        )
        out: dict[str, list[str]] = {}
        async with tenant_tx(self.engine) as c:
            for step, approver in (await c.execute(q)).all():
                out.setdefault(str(step), []).append(str(approver))
        return out

    async def approvals_of_input(self, thread_id: str, step: str, digest: str) -> list[tuple[str, str]]:
        """(approver, approved at) for every approval of this exact input."""
        a = review_approvals.c
        q = sa.select(a.approver, a.approved_at).where(a.thread_id == thread_id, a.step == step, a.input_hash == digest)
        async with tenant_tx(self.engine) as c:
            return [(str(r.approver), str(r.approved_at)) for r in (await c.execute(q)).all()]
