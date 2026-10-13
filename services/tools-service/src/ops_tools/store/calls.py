"""gateway_calls: one row per call the gateway received, allowed or refused, with OPA's reasons."""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_store import Guarantee

metadata = sa.MetaData()

gateway_calls = sa.Table(
    "gateway_calls",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tool", sa.String(64), nullable=False),
    sa.Column("access", sa.String(32), nullable=False),
    sa.Column("input_hash", sa.String(64), nullable=False),
    sa.Column("idempotency_key", sa.String(200), nullable=False),
    sa.Column("thread_id", sa.String(64)),
    sa.Column("step", sa.String(200)),
    sa.Column("sub", sa.String(200), nullable=False),
    sa.Column("act", sa.String(200)),
    sa.Column("decision", sa.String(8), nullable=False),
    sa.Column("reasons", sa.JSON, nullable=False),
    sa.Column("approvers", sa.JSON, nullable=False),
    sa.Column("outcome", sa.String(16), nullable=False),
    # True on the one row whose call ran the tool; unique per (thread_id, step, tool, input_hash) in migration 0006.
    sa.Column("effect", sa.Boolean, nullable=False),
    sa.Column("output", sa.JSON),
    sa.Column("view", sa.JSON),
    sa.Column("created_at", sa.String(32), nullable=False),
    # The registry module the tool belongs to; null for a tool the registry does not know.
    sa.Column("module_id", sa.String(64)),
    sa.Column("latency_ms", sa.Integer),
    # {code, message} when the call was refused or failed; never secret material.
    sa.Column("error", sa.JSON),
    # A fingerprint of the approval token that allowed a write, never the token itself.
    sa.Column("approval_token_id", sa.String(64)),
    # On a replayed write, the call whose result it returned.
    sa.Column("replay_of", sa.String(64)),
)


class LeaseSupersededError(RuntimeError):
    """A write call whose lease generation is below the thread's fence, or with none on a fenced thread."""


gateway_fences = sa.Table(
    "gateway_fences",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("generation", sa.BigInteger(), nullable=False),
)


class CallLog:
    # A call is claimed once per key and a thread's fence only rises (CAS); the fence and the write it guards share
    # one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def _fence(self, c: AsyncConnection, thread_id: str, generation: int | None) -> bool:
        """Applies the thread's fence, the highest lease generation a write call has carried, inside the caller's
        transaction. True when the call may go on. A call without a generation passes only on a thread that was
        never fenced (chat turns, direct callers). The gateway keeps this table itself; it never reads the Runtime's
        leases."""
        if generation is None:
            q = sa.select(gateway_fences.c.generation).where(gateway_fences.c.thread_id == thread_id)
            return (await c.execute(q)).first() is None
        insert = (postgresql.insert if self.engine.dialect.name == "postgresql" else sqlite.insert)(gateway_fences)
        stmt = (
            insert.values(thread_id=thread_id, generation=generation)
            .on_conflict_do_update(
                index_elements=["thread_id"],
                set_={"generation": sa.func.greatest(gateway_fences.c.generation, generation)},
            )
            .returning(gateway_fences.c.generation)
        )
        return int((await c.execute(stmt)).scalar_one()) <= generation

    async def raise_fence(self, thread_id: str, generation: int) -> int:
        """Raises the thread's fence to `generation` unless it is already higher, and returns the fence. A lower
        generation leaves it as it is; the caller compares the result with what it sent."""
        async with self.engine.begin() as c:
            insert = (postgresql.insert if self.engine.dialect.name == "postgresql" else sqlite.insert)(gateway_fences)
            stmt = (
                insert.values(thread_id=thread_id, generation=generation)
                .on_conflict_do_update(
                    index_elements=["thread_id"],
                    set_={"generation": sa.func.greatest(gateway_fences.c.generation, generation)},
                )
                .returning(gateway_fences.c.generation)
            )
            return int((await c.execute(stmt)).scalar_one())

    async def record(self, **row: Any) -> None:
        async with self.engine.begin() as c:
            await c.execute(gateway_calls.insert().values(effect=False, **row))

    async def claim(self, *, generation: int | None, **row: Any) -> dict[str, Any] | None:
        """Checks the thread's fence and inserts the row that will carry this write's side effect, in one transaction
        (ADR-0016): a superseded caller raises LeaseSupersededError before the dedup lookup, so it is refused, never
        answered with the new owner's result. Returns None when this call won the claim, or the first call's row when
        the same write already has one."""
        async with self.engine.begin() as c:
            if row["thread_id"] and not await self._fence(c, row["thread_id"], generation):
                raise LeaseSupersededError("lease superseded")
            try:
                async with c.begin_nested():
                    await c.execute(gateway_calls.insert().values(effect=True, outcome="running", **row))
                return None
            except IntegrityError:
                q = gateway_calls.select().where(
                    gateway_calls.c.effect,
                    gateway_calls.c.thread_id == row["thread_id"],
                    gateway_calls.c.step == row["step"],
                    gateway_calls.c.tool == row["tool"],
                    gateway_calls.c.input_hash == row["input_hash"],
                )
                first = (await c.execute(q)).mappings().first()
                assert first is not None, "the unique index conflicted, so the first row exists"
                return dict(first)

    async def refuse_claimed(self, call_id: str, *, reasons: list[str], error: dict[str, Any], latency_ms: int) -> None:
        """Turns a claimed write that was refused before it ran (its rate limit) into a refused row and gives up the
        claim, so a retry after the window can claim and run it instead of replaying the refusal."""
        async with self.engine.begin() as c:
            await c.execute(
                gateway_calls.update()
                .where(gateway_calls.c.id == call_id)
                .values(
                    effect=False,
                    outcome="refused",
                    decision="deny",
                    reasons=reasons,
                    error=error,
                    latency_ms=latency_ms,
                )
            )

    async def finish(self, call_id: str, *, outcome: str, output: Any, view: Any, **extra: Any) -> None:
        """Completes a claimed write's row; `extra` carries the latency and any error."""
        async with self.engine.begin() as c:
            await c.execute(
                gateway_calls.update()
                .where(gateway_calls.c.id == call_id)
                .values(outcome=outcome, output=output, view=view, **extra)
            )

    async def for_thread(self, thread_id: str) -> list[dict[str, Any]]:
        q = gateway_calls.select().where(gateway_calls.c.thread_id == thread_id).order_by(gateway_calls.c.created_at)
        async with self.engine.connect() as c:
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def search(
        self,
        *,
        tools: list[str] | None = None,
        module_ids: list[str] | None = None,
        thread_id: str | None = None,
        decision: str | None = None,
        since: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Calls newest first with the total that match; `since` is an ISO time, compared as text like created_at."""
        where: list[sa.ColumnElement[bool]] = []
        if tools is not None:
            where.append(gateway_calls.c.tool.in_(tools))
        if module_ids is not None:
            where.append(gateway_calls.c.module_id.in_(module_ids))
        if thread_id:
            where.append(gateway_calls.c.thread_id == thread_id)
        if decision:
            where.append(gateway_calls.c.decision == decision)
        if since:
            where.append(gateway_calls.c.created_at >= since)
        q = gateway_calls.select().where(*where).order_by(gateway_calls.c.created_at.desc()).offset(offset).limit(limit)
        total = sa.select(sa.func.count()).select_from(gateway_calls).where(*where)
        async with self.engine.connect() as c:
            rows = [dict(r) for r in (await c.execute(q)).mappings()]
            return rows, int((await c.execute(total)).scalar_one())

    async def traffic(self, module_ids: list[str], since: str) -> dict[tuple[str, str | None], dict[str, Any]]:
        return await traffic(self.engine, module_ids, since)

    async def daily(self, module_id: str, since: str) -> dict[str, dict[str, Any]]:
        return await daily(self.engine, module_id, since)


# Calls that reached the system behind the operation. A refusal never left the gateway and a replay returned the first
# call's result, so neither counts toward traffic, errors or latency; refusals are counted on their own (denied24h).
RAN = ("ok", "error")


def _ran_since(module_ids: list[str], since: str) -> list[sa.ColumnElement[bool]]:
    return [
        gateway_calls.c.module_id.in_(module_ids),
        gateway_calls.c.created_at >= since,
        gateway_calls.c.outcome.in_(RAN),
    ]


async def traffic(
    engine: AsyncEngine, module_ids: list[str], since: str
) -> dict[tuple[str, str | None], dict[str, Any]]:
    """Calls, errors and p95 latency since `since`, per (module, operation) and per module (operation None), in one
    aggregate: GROUPING SETS gives the module's p95 over all its calls, which the operations' p95s cannot."""
    if not module_ids:
        return {}
    c = gateway_calls.c
    q = (
        sa.select(
            c.module_id,
            c.tool,
            sa.func.grouping(c.tool).label("whole"),
            sa.func.count().label("calls"),
            sa.func.count().filter(c.outcome == "error").label("errors"),
            sa.func.percentile_cont(0.95).within_group(c.latency_ms).label("p95"),
        )
        .where(*_ran_since(module_ids, since))
        .group_by(sa.func.grouping_sets(sa.tuple_(c.module_id, c.tool), sa.tuple_(c.module_id)))
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return {
        (r["module_id"], None if r["whole"] else r["tool"]): {
            "calls": int(r["calls"]),
            "errors": int(r["errors"]),
            "p95Ms": round(r["p95"] or 0),
        }
        for r in rows
    }


async def daily(engine: AsyncEngine, module_id: str, since: str) -> dict[str, dict[str, Any]]:
    """Per UTC day since `since`: calls, errors and p95 latency. created_at is ISO text, so its first ten characters
    are the day."""
    c = gateway_calls.c
    day = sa.func.substr(c.created_at, 1, 10)
    q = (
        sa.select(
            day.label("day"),
            sa.func.count().label("calls"),
            sa.func.count().filter(c.outcome == "error").label("errors"),
            sa.func.percentile_cont(0.95).within_group(c.latency_ms).label("p95"),
        )
        .where(*_ran_since([module_id], since))
        .group_by(day)
    )
    async with engine.connect() as conn:
        rows = (await conn.execute(q)).mappings().all()
    return {
        r["day"]: {"count": int(r["calls"]), "errors": int(r["errors"]), "p95Ms": round(r["p95"] or 0)} for r in rows
    }
