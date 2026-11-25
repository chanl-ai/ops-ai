"""Model calls, one record each: what the budget sums, what replay answers from, and what the journal shows.

A kernel model request in a graph run is recorded by the kernel's model wrapper (api/model_ledger.py) with its
alias, tokens, latency, thread, run, step, its replay key (`task`), the request's hash and its response. The key is
the LangGraph task for a chat turn and the step id (run:node:iteration) for a workflow step, whose thread is its run.
A chat-graph model call outside the kernel (classify, extract, grade) is recorded by the metering wrapper with its
usage and no response. Replay looks a response up by (thread, task, request hash): a re-run after a crash keeps its
key and is answered from the record, while a new step (a regenerate) has a new key and calls the model again.

Rows are written as each call returns and are not fenced: a call made by a node that later crashed was paid for.
Cost is stored as integer millionths of the currency unit so sums are exact on SQLite and PostgreSQL alike.

A call checked against a budget is in the table before it runs, as a reservation: a row with `reserved_until` set,
holding one call and an estimate of its tokens and cost (store/usage.py `UsageLedger.reserve`). When the call returns
the same row becomes its record, in one statement, so the call is never counted twice or not at all; a call that
failed has its row deleted. A reservation is not a recorded call: replay, the journal and the spend a person is shown
read only rows with no `reserved_until`, and a budget check counts a reservation only until that time, so a process
that died mid-call holds budget for a while and not for good.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_metering import MICRO, Totals
from ops_service_kit.http import Out
from ops_service_kit.ids import new_id, now_iso
from ops_store import Guarantee
from ops_store.dialect import db_now, insert_ignore
from ops_store.rows import rows
from ops_store.schema import TENANT_SCOPED, system

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

# Why the side tables of model_call_records and thread_budgets hold no tenant.
UNATTRIBUTED = "unattributed rows kept from before tenancy: a thread gone and no other row naming its tenant (0104)"

model_call_records = sa.Table(
    "model_call_records",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("step", sa.String(120), nullable=False),
    # The replay key with the request hash: the chat turn's LangGraph task, or the workflow step's id.
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
    # Set while the row is a reservation for a call still running, to the time a budget check stops counting it;
    # NULL on a recorded call (migration 0120).
    sa.Column("reserved_until", sa.String(40)),
    # The thread's tenant, set from the request's or loop's context, never from a body (migration 0104).
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant),
    # One recorded response per task and request: the first one written wins (CAS).
    sa.UniqueConstraint("thread_id", "task", "request_hash", name="uq_model_call_replay"),
    sa.Index("ix_model_call_records_thread_id", "thread_id"),
    info=TENANT_SCOPED,
)

# The calls recorded before 0104 whose thread is gone and that nothing else names a tenant for: kept, as recorded spend,
# for operators. No store reads or writes it, and neither tenant transactions nor the SQL Server runtime user hold a
# grant on it, so no tenant reads it.
model_call_records_unattributed = sa.Table(
    "model_call_records_unattributed",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("thread_id", sa.String(64), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("step", sa.String(120), nullable=False),
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
    sa.Column("moved_at", sa.DateTime(timezone=True), nullable=False, server_default=db_now()),
    info=system(UNATTRIBUTED),
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


class ModelCallOut(Out):
    """One recorded model call, as the journal and tests read it."""

    id: str
    thread_id: str
    run_id: str | None
    step: str
    task: str | None
    kind: str
    model_alias: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_micros: int
    latency_ms: int | None
    request_hash: str | None
    response: Any
    created_at: str


_m = model_call_records.c
CALL_COLUMNS = (
    _m.id,
    _m.thread_id,
    _m.run_id,
    _m.step,
    _m.task,
    _m.kind,
    _m.model_alias,
    _m.calls,
    _m.input_tokens,
    _m.output_tokens,
    _m.cost_micros,
    _m.latency_ms,
    _m.request_hash,
    _m.response,
    _m.created_at,
)


class ModelCallLedger(RuntimeStore):
    # Replay depends on the first response recorded for a (thread, task, request) winning (CAS). A record is one
    # statement, and so is a reservation becoming its record; the transaction that checks a budget and writes the
    # reservation is the usage ledger's (store/usage.py).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    async def record(self, call: ModelCall, *, settles: str | None = None) -> bool:
        """Writes the record; False when a response for the same task and request is already there. `settles` is the
        id of the reservation the call ran under: that row becomes the record, so the call is counted once throughout.
        A reservation already gone (it lapsed during a long call) leaves the record to be written as a new row."""
        if settles is not None and (settled := await self._settle(settles, call)) is not None:
            return settled
        values = {"id": new_id("mc"), "created_at": now_iso(), "tenant_id": current_tenant(), **call.__dict__}
        stmt: sa.Executable = (
            insert_ignore(self.engine, model_call_records, values, keys=["thread_id", "task", "request_hash"])
            if call.request_hash is not None
            else model_call_records.insert().values(**values)
        )
        try:
            async with self.tx() as c, self.attempt(c):
                return (await c.execute(stmt)).rowcount != 0
        except IntegrityError:
            return False

    async def _settle(self, reservation_id: str, call: ModelCall) -> bool | None:
        """Turns the reservation into the call's record. None when the reservation is gone; False when a response
        for the same task and request is already recorded, and the reservation is then dropped."""
        held = sa.and_(_m.id == reservation_id, _m.reserved_until.is_not(None))
        values = {"created_at": now_iso(), "reserved_until": None, **call.__dict__}
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    done = await c.execute(model_call_records.update().where(held).values(**values))
            except IntegrityError:
                await c.execute(model_call_records.delete().where(held))
                return False
        return True if done.rowcount else None

    async def release(self, reservation_id: str) -> None:
        """Drops a reservation whose call did not return; a row already settled is a record and is left alone."""
        held = sa.and_(_m.id == reservation_id, _m.reserved_until.is_not(None))
        async with self.tx() as c:
            await c.execute(model_call_records.delete().where(held))

    async def response(self, thread_id: str, task: str, request_hash: str) -> Any:
        m = model_call_records.c
        q = sa.select(m.response).where(
            m.thread_id == thread_id, m.task == task, m.request_hash == request_hash, m.reserved_until.is_(None)
        )
        async with self.tx() as c:
            return (await c.execute(q)).scalar_one_or_none()

    async def calls(self, thread_id: str) -> list[ModelCallOut]:
        q = (
            sa.select(*CALL_COLUMNS)
            .where(_m.thread_id == thread_id, _m.reserved_until.is_(None))
            .order_by(_m.created_at, _m.id)
        )
        async with self.tx() as c:
            return await rows(c, q, ModelCallOut)

    async def sums(self, thread_id: str, *, by_run: bool) -> dict[str | None, Totals]:
        m = model_call_records.c
        cols = [
            sa.func.coalesce(sa.func.sum(m.calls), 0),
            sa.func.coalesce(sa.func.sum(m.input_tokens), 0),
            sa.func.coalesce(sa.func.sum(m.output_tokens), 0),
            sa.func.coalesce(sa.func.sum(m.cost_micros), 0),
        ]
        key = m.run_id if by_run else sa.null()
        q = sa.select(key, *cols).where(m.thread_id == thread_id, m.reserved_until.is_(None))
        if by_run:
            q = q.group_by(m.run_id)
        async with self.tx() as c:
            rows: list[tuple[Any, ...]] = [tuple(r) for r in (await c.execute(q)).all()]
        return {r[0]: Totals(int(r[1]), int(r[2]), int(r[3]), MICRO * int(r[4])) for r in rows}
