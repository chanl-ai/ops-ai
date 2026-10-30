"""Model calls, one record each: what the budget sums, what replay answers from, and what the journal shows.

A kernel model request in a graph run is recorded by the kernel's model wrapper (api/model_ledger.py) with its
alias, tokens, latency, thread, run, step, the LangGraph task it ran in, the request's hash and its response. A
workflow model call (classify, extract, draft, grade) is recorded by the metering wrapper with its usage and no
response. Replay looks a response up by (thread, task, request hash): a node re-run after a crash keeps its task id
and is answered from the record, while a new step (a regenerate) has a new task id and calls the model again.

Rows are written as each call returns and are not fenced: a call made by a node that later crashed was paid for.
Cost is stored as integer millionths of the currency unit so sums are exact on SQLite and PostgreSQL alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_metering import MICRO, Totals
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import insert_ignore

from .base import metadata

model_call_records = sa.Table(
    "model_call_records",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("step", sa.String(120), nullable=False),
    # The LangGraph task the call ran in; with the request hash, the replay key.
    sa.Column("task", sa.String(200)),
    sa.Column("kind", sa.String(40), nullable=False),
    sa.Column("model_alias", sa.String(120), nullable=False),
    sa.Column("calls", sa.Integer(), nullable=False),
    sa.Column("input_tokens", sa.BigInteger(), nullable=False),
    sa.Column("output_tokens", sa.BigInteger(), nullable=False),
    sa.Column("cost_micros", sa.BigInteger(), nullable=False),
    sa.Column("latency_ms", sa.Integer()),
    sa.Column("request_hash", sa.String(64)),
    sa.Column("response", sa.JSON()),
    sa.Column("created_at", sa.String(40), nullable=False),
    # One recorded response per task and request: the first one written wins (CAS).
    sa.UniqueConstraint("thread_id", "task", "request_hash", name="uq_model_call_replay"),
    sa.Index("ix_model_call_records_thread_id", "thread_id"),
)


@dataclass(frozen=True)
class ModelCall:
    thread_id: str
    run_id: str | None
    step: str
    kind: str
    model_alias: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    latency_ms: int | None = None
    task: str | None = None
    request_hash: str | None = None
    response: Any = None


class ModelCallLedger:
    # Replay depends on the first response recorded for a (thread, task, request) winning (CAS); a record and the sum
    # a budget check reads are each one statement, so no transaction spans them.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def record(self, call: ModelCall) -> bool:
        """Writes the record; False when a response for the same task and request is already there."""
        values = {"id": new_id("mc"), "created_at": now_iso(), **call.__dict__}
        stmt: sa.Executable = (
            insert_ignore(self.engine, model_call_records, values, keys=["thread_id", "task", "request_hash"])
            if call.request_hash is not None
            else model_call_records.insert().values(**values)
        )
        try:
            async with self.engine.begin() as c:
                return (await c.execute(stmt)).rowcount != 0
        except IntegrityError:
            return False

    async def response(self, thread_id: str, task: str, request_hash: str) -> Any:
        m = model_call_records.c
        q = sa.select(m.response).where(m.thread_id == thread_id, m.task == task, m.request_hash == request_hash)
        async with self.engine.connect() as c:
            return (await c.execute(q)).scalar_one_or_none()

    async def calls(self, thread_id: str) -> list[dict[str, Any]]:
        q = model_call_records.select().where(model_call_records.c.thread_id == thread_id)
        async with self.engine.connect() as c:
            rows = (await c.execute(q.order_by(model_call_records.c.created_at))).mappings().all()
        return [dict(r) for r in rows]

    async def sums(self, thread_id: str, *, by_run: bool) -> dict[str | None, Totals]:
        m = model_call_records.c
        cols = [
            sa.func.coalesce(sa.func.sum(m.calls), 0),
            sa.func.coalesce(sa.func.sum(m.input_tokens), 0),
            sa.func.coalesce(sa.func.sum(m.output_tokens), 0),
            sa.func.coalesce(sa.func.sum(m.cost_micros), 0),
        ]
        key = m.run_id if by_run else sa.null()
        q = sa.select(key, *cols).where(m.thread_id == thread_id)
        if by_run:
            q = q.group_by(m.run_id)
        async with self.engine.connect() as c:
            rows: list[tuple[Any, ...]] = [tuple(r) for r in (await c.execute(q)).all()]
        return {r[0]: Totals(int(r[1]), int(r[2]), int(r[3]), MICRO * int(r[4])) for r in rows}
