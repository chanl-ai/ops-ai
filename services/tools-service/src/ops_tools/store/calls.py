"""gateway_calls: one row per call the gateway received, allowed or refused, with OPA's reasons."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_service_kit.http import Out
from ops_service_kit.ids import new_id
from ops_store import Guarantee
from ops_store.dialect import dialect_of, insert_ignore, lock_key
from ops_store.rows import one, rows
from ops_store.schema import TENANT_SCOPED
from ops_store.store import Store

from .tenancy import ROLE

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
    # True on the one row whose call ran the tool (see effect_scope).
    sa.Column("effect", sa.Boolean, nullable=False),
    # Which write this row acts for: "thread:<id>" or "none" on the one row carrying a write's side effect,
    # "row:<call id>" on every other row. Unique with tenant, step, tool and input hash (migration 0017), so exactly one
    # row per approved write acts, on any database (a partial index would hold on PostgreSQL only).
    sa.Column("effect_scope", sa.String(80), nullable=False),
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
    # The tenant the call was made in (the caller's). Every read filters on it; a row with none (older than the
    # column, on no known module) is read by nobody.
    sa.Column("tenant_id", sa.String(64), index=True),
    # The team the call was made in: the caller's acting team, or its module's team for a caller with none (tools
    # migration 0051). Usage reads only its own team's rows; a row with none is read by nobody.
    sa.Column("team_id", sa.String(64)),
    # The kind of run the call was made in (test or live) and which connection signed it in;
    # null for a call that used no connection.
    sa.Column("environment", sa.String(16)),
    sa.Column("connection_id", sa.String(64)),
    # Whom a verified acting-for token named (an email), and whose sign-in signed the call: person or team.
    sa.Column("acting_for", sa.String(320)),
    sa.Column("credential", sa.String(16)),
    # The route that took the call, api (POST /v1/calls) or mcp, and the client's own name for itself over MCP, a claim
    # shown as one; null on rows older than the columns.
    sa.Column("channel", sa.String(16)),
    sa.Column("client_name", sa.String(120)),
    # The assistant an MCP token was issued to (platform-service's client id), which a person allowed by name;
    # client_name above stays what the assistant says about itself.
    sa.Column("client_id", sa.String(64)),
    # The MCP link the call came through (mcp_links.id); null for the team's whole address and every other channel.
    sa.Column("link_id", sa.String(64)),
    # The caller's own name (a person's or a key's) when the call was made, so the log names them, not their id.
    sa.Column("caller_name", sa.String(320)),
    sa.Index("ix_gateway_calls_link_created", "link_id", "created_at"),
    sa.Index("ix_gateway_calls_module_created", "module_id", "created_at"),
    sa.Index("ix_gateway_calls_thread_id", "thread_id"),
    # An approved write acts once per effect scope (tools migration 0017).
    sa.Index("ux_gateway_calls_effect_scope", "tenant_id", "effect_scope", "step", "tool", "input_hash", unique=True),
    # Held to its tenant by the database (tools_0080); the team a call acted in is a filter of the reads, since a run's
    # call on a module every team shares is logged in the calling team.
    info=TENANT_SCOPED,
)


class GatewayCall(Out):
    """One row of the call log, every column."""

    id: str
    tool: str
    access: str
    input_hash: str
    idempotency_key: str
    thread_id: str | None
    step: str | None
    sub: str
    act: str | None
    decision: str
    # Written from OPA's answer and an approval token's claims: JSON, read as text.
    reasons: list[JsonValue]
    approvers: list[JsonValue]
    outcome: str
    effect: bool
    effect_scope: str
    output: JsonValue
    view: JsonValue
    created_at: str
    module_id: str | None
    latency_ms: int | None
    error: dict[str, JsonValue] | None
    approval_token_id: str | None
    replay_of: str | None
    tenant_id: str | None
    team_id: str | None
    environment: str | None
    connection_id: str | None
    acting_for: str | None
    credential: str | None
    channel: str | None
    client_name: str | None
    client_id: str | None
    link_id: str | None
    caller_name: str | None


class CallStats(Out):
    """Calls, errors and p95 latency of a module or one of its operations."""

    calls: int
    errors: int
    p95_ms: int


class DayStats(Out):
    """Calls, errors and p95 latency of one UTC day."""

    count: int
    errors: int
    p95_ms: int


# A write still `running` after this long belongs to a gateway that stopped mid-execute: whether the system acted is
# not known, so it reads as `lost`, never as still running (a workflow then takes its error port, never re-sends).
RUNNING_EXPIRY = timedelta(minutes=5)


class CallAbandonedError(RuntimeError):
    """The caller abandoned this key (it found no record of the call and moved on), so the call must not run."""


def _effect_scope(thread_id: str | None) -> str:
    return f"thread:{thread_id}" if thread_id else "none"


def _own(call_id: str) -> str:
    """The scope of a row that carries no side effect: its own id, so it never meets the unique index."""
    return f"row:{call_id}"


def _iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def _key_lock(c: AsyncConnection, key: str) -> None:
    """Serialises the claim and the abandon of one idempotency key until the transaction ends."""
    await lock_key(c, f"call:{key}")


async def _raised(c: AsyncConnection, tenant_id: str, thread_id: str, generation: int) -> int:
    """Raises the tenant's fence on the thread to `generation` unless it is higher, in the caller's transaction, and
    returns the fence. The insert leaves an existing row alone and the update only raises it, so two raises at once
    leave the higher generation on any database."""
    f = gateway_fences.c
    mine = (f.tenant_id == tenant_id, f.thread_id == thread_id)
    row = {"tenant_id": tenant_id, "thread_id": thread_id, "generation": generation}
    await c.execute(insert_ignore(c, gateway_fences, row, keys=["tenant_id", "thread_id"]))
    await c.execute(gateway_fences.update().where(*mine, f.generation < generation).values(generation=generation))
    return int((await c.execute(sa.select(f.generation).where(*mine))).scalar_one())


class LeaseSupersededError(RuntimeError):
    """A write call whose lease generation is below the thread's fence, or with none on a fenced thread."""


gateway_fences = sa.Table(
    "gateway_fences",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("generation", sa.BigInteger(), nullable=False),
    # A run's lease generation, checked and raised inside the claim of its tenant's write (tools_0082).
    info=TENANT_SCOPED,
)


class CallLog(Store):
    # A call is claimed once per key and a thread's fence only rises (CAS); the fence and the write it guards share
    # one transaction (TRANSACTION).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})
    role = ROLE

    async def _fence(self, c: AsyncConnection, tenant_id: str, thread_id: str, generation: int | None) -> bool:
        """Applies the thread's fence, the highest lease generation a write call has carried, inside the caller's
        transaction. True when the call may go on. A call without a generation passes only on a thread that was
        never fenced (chat turns, direct callers). The gateway keeps this table itself; it never reads the Runtime's
        leases."""
        if generation is None:
            q = sa.select(gateway_fences.c.generation).where(
                gateway_fences.c.tenant_id == tenant_id, gateway_fences.c.thread_id == thread_id
            )
            return (await c.execute(q)).first() is None
        return await _raised(c, tenant_id, thread_id, generation) <= generation

    async def raise_fence(self, tenant_id: str, thread_id: str, generation: int) -> int:
        """Raises the tenant's fence on the thread to `generation` unless it is already higher, and returns the fence.
        A lower generation leaves it as it is; the caller compares the result with what it sent."""
        async with self.tx() as c:
            return await _raised(c, tenant_id, thread_id, generation)

    async def record(self, **row: Any) -> None:
        async with self.tx() as c:
            await c.execute(gateway_calls.insert().values(effect=False, effect_scope=_own(row["id"]), **row))

    async def claim(self, *, generation: int | None, **row: Any) -> GatewayCall | None:
        """Checks the thread's fence and inserts the row that will carry this write's side effect, in one transaction
        (ADR-0016): a superseded caller raises LeaseSupersededError before the dedup lookup, so it is refused, never
        answered with the new owner's result. Returns None when this call won the claim, or the first call's row when
        the same write already has one."""
        async with self.tx() as c:
            if row["thread_id"] and not await self._fence(c, row["tenant_id"], row["thread_id"], generation):
                raise LeaseSupersededError("lease superseded")
            await _key_lock(c, row["idempotency_key"])
            abandoned = sa.select(gateway_calls.c.id).where(
                gateway_calls.c.tenant_id == row["tenant_id"],
                gateway_calls.c.idempotency_key == row["idempotency_key"],
                gateway_calls.c.outcome == "abandoned",
            )
            if (await c.execute(abandoned)).first() is not None:
                raise CallAbandonedError(row["idempotency_key"])
            try:
                async with self.attempt(c):
                    scope = _effect_scope(row["thread_id"])
                    await c.execute(
                        gateway_calls.insert().values(effect=True, effect_scope=scope, outcome="running", **row)
                    )
                return None
            except IntegrityError:
                q = gateway_calls.select().where(
                    gateway_calls.c.tenant_id == row["tenant_id"],
                    gateway_calls.c.effect_scope == _effect_scope(row["thread_id"]),
                    gateway_calls.c.step == row["step"],
                    gateway_calls.c.tool == row["tool"],
                    gateway_calls.c.input_hash == row["input_hash"],
                )
                first = await one(c, q, GatewayCall)
                assert first is not None, "the unique index conflicted, so the first row exists"
                return first

    async def refuse_claimed(self, call_id: str, *, reasons: list[str], error: dict[str, Any], latency_ms: int) -> None:
        """Turns a claimed write that was refused before it ran (its rate limit) into a refused row and gives up the
        claim, so a retry after the window can claim and run it instead of replaying the refusal."""
        async with self.tx() as c:
            await c.execute(
                gateway_calls.update()
                .where(gateway_calls.c.id == call_id)
                .values(
                    effect=False,
                    # Gives up the claim, so a retry after the window can claim the write and run it.
                    effect_scope=_own(call_id),
                    outcome="refused",
                    decision="deny",
                    reasons=reasons,
                    error=error,
                    latency_ms=latency_ms,
                )
            )

    async def finish(
        self, call_id: str, *, outcome: str, output: Any, view: Any, unsent: bool = False, **extra: Any
    ) -> None:
        """Completes a claimed write's row; `extra` carries the latency and any error. `unsent`: the write failed before
        anything was sent, so the claim is given back and the same write sent again runs instead of replaying this."""
        released = {"effect": False, "effect_scope": _own(call_id)} if unsent else {}
        async with self.tx() as c:
            await c.execute(
                gateway_calls.update()
                .where(gateway_calls.c.id == call_id)
                .values(outcome=outcome, output=output, view=view, **released, **extra)
            )

    async def abandon(
        self, *, tenant_id: str, key: str, tool: str, thread_id: str | None, sub: str
    ) -> GatewayCall | None:
        """The call sent under `key` when the gateway has one; otherwise the key is marked abandoned, in the same
        transaction under the key's lock, so a claim of it arriving later is refused (CallAbandonedError)."""
        mine = (gateway_calls.c.tenant_id == tenant_id, gateway_calls.c.idempotency_key == key)
        async with self.tx() as c:
            await _key_lock(c, key)
            q = (
                gateway_calls.select()
                .where(*mine, gateway_calls.c.outcome != "abandoned")
                .order_by(gateway_calls.c.effect.desc(), gateway_calls.c.created_at, gateway_calls.c.id)
                .limit(1)
            )
            found = await one(c, q, GatewayCall)
            if found is not None:
                return found
            marked = sa.select(gateway_calls.c.id).where(*mine, gateway_calls.c.outcome == "abandoned")
            if (await c.execute(marked)).first() is None:
                abandoned_id = new_id("gwc")
                await c.execute(
                    gateway_calls.insert().values(
                        id=abandoned_id,
                        tenant_id=tenant_id,
                        tool=tool,
                        access="write",
                        input_hash="",
                        idempotency_key=key,
                        thread_id=thread_id,
                        step=key,
                        sub=sub,
                        decision="deny",
                        reasons=["abandoned by its caller, which found no record of it"],
                        approvers=[],
                        outcome="abandoned",
                        effect=False,
                        effect_scope=_own(abandoned_id),
                        created_at=_iso(datetime.now(UTC)),
                    )
                )
            return None

    async def expire_running(self, *, tenant_id: str, key: str | None = None) -> None:
        """Marks writes still running past RUNNING_EXPIRY as lost (see RUNNING_EXPIRY)."""
        cutoff = _iso(datetime.now(UTC) - RUNNING_EXPIRY)
        where = [
            gateway_calls.c.tenant_id == tenant_id,
            gateway_calls.c.outcome == "running",
            gateway_calls.c.created_at < cutoff,
        ]
        if key is not None:
            where.append(gateway_calls.c.idempotency_key == key)
        error = {"code": "CALL_LOST", "message": "the gateway stopped before the call finished; it may have run"}
        async with self.tx() as c:
            await c.execute(gateway_calls.update().where(*where).values(outcome="lost", error=error))

    async def get(self, call_id: str, *, tenant_id: str, team_ids: list[str]) -> GatewayCall | None:
        """One call by its id, as the log recorded it, made in one of `team_ids`; None when there is none there."""
        q = gateway_calls.select().where(
            gateway_calls.c.id == call_id, gateway_calls.c.tenant_id == tenant_id, gateway_calls.c.team_id.in_(team_ids)
        )
        async with self.tx() as c:
            return await one(c, q, GatewayCall)

    async def for_thread(self, thread_id: str, *, tenant_id: str) -> list[GatewayCall]:
        q = (
            gateway_calls.select()
            .where(gateway_calls.c.thread_id == thread_id, gateway_calls.c.tenant_id == tenant_id)
            .order_by(gateway_calls.c.created_at, gateway_calls.c.id)
        )
        async with self.tx() as c:
            return await rows(c, q, GatewayCall)

    async def search(
        self,
        *,
        tenant_id: str,
        team_ids: list[str],
        tools: list[str] | None = None,
        module_ids: list[str] | None = None,
        moduleless: bool = False,
        thread_id: str | None = None,
        decision: str | None = None,
        since: str | None = None,
        until: str | None = None,
        key: str | None = None,
        call_id: str | None = None,
        link_id: str | None = None,
        sub: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[GatewayCall], int]:
        """Calls made in `team_ids` (the caller's team), newest first, with the total that match; `since` is an ISO
        time, compared as text like created_at. The team is the one the call acted in, not the module's: a module every
        team shares holds each team's calls, and each team reads only its own. `moduleless` also keeps the team's calls
        on no module (a tool no module holds, refused) beside `module_ids`."""
        where: list[sa.ColumnElement[bool]] = [
            gateway_calls.c.tenant_id == tenant_id,
            gateway_calls.c.team_id.in_(team_ids),
        ]
        if tools is not None:
            where.append(gateway_calls.c.tool.in_(tools))
        if module_ids is not None:
            listed = gateway_calls.c.module_id.in_(module_ids)
            where.append(sa.or_(listed, gateway_calls.c.module_id.is_(None)) if moduleless else listed)
        if thread_id:
            where.append(gateway_calls.c.thread_id == thread_id)
        if decision:
            where.append(gateway_calls.c.decision == decision)
        if key:
            where.append(gateway_calls.c.idempotency_key == key)
        if call_id:
            where.append(gateway_calls.c.id == call_id)
        if link_id:
            where.append(gateway_calls.c.link_id == link_id)
        if sub is not None:
            where.append(gateway_calls.c.sub == sub)
        if since:
            where.append(gateway_calls.c.created_at >= since)
        if until:
            where.append(gateway_calls.c.created_at < until)
        q = gateway_calls.select().where(*where).order_by(gateway_calls.c.created_at.desc()).offset(offset).limit(limit)
        total = sa.select(sa.func.count()).select_from(gateway_calls).where(*where)
        async with self.tx() as c:
            found = await rows(c, q, GatewayCall)
            return found, int((await c.execute(total)).scalar_one())

    async def made_for(
        self, person: str, module_ids: list[str], since: str, *, tenant_id: str, team_id: str
    ) -> dict[str, int]:
        """How many calls ran acting for `person` (their email) in the team since `since`, by module: a person's own
        count, never another's calls, the team account's runs that named nobody, or calls the gateway refused."""
        if not module_ids:
            return {}
        q = (
            sa.select(gateway_calls.c.module_id, sa.func.count())
            .where(
                gateway_calls.c.tenant_id == tenant_id,
                gateway_calls.c.team_id == team_id,
                gateway_calls.c.acting_for == person,
                gateway_calls.c.module_id.in_(module_ids),
                gateway_calls.c.created_at >= since,
                gateway_calls.c.outcome != "refused",
            )
            .group_by(gateway_calls.c.module_id)
        )
        async with self.tx() as c:
            return {str(m): int(n) for m, n in (await c.execute(q)).all()}

    async def traffic(
        self, module_ids: list[str], since: str, *, tenant_id: str, team_ids: list[str]
    ) -> dict[tuple[str, str | None], CallStats]:
        async with self.tx() as c:
            return await traffic(c, module_ids, since, tenant_id=tenant_id, team_ids=team_ids)

    async def daily(self, module_id: str, since: str, *, tenant_id: str, team_ids: list[str]) -> dict[str, DayStats]:
        async with self.tx() as c:
            return await daily(c, module_id, since, tenant_id=tenant_id, team_ids=team_ids)


# Calls that reached the system behind the operation. A refusal never left the gateway and a replay returned the first
# call's result, so neither counts toward traffic, errors or latency; refusals are counted on their own (denied24h).
RAN = ("ok", "error")


def _p95() -> sa.WithinGroup[Any]:
    # SQL Server takes the fraction only as a literal, so it is rendered into the statement, never bound.
    return sa.func.percentile_cont(sa.literal(0.95, literal_execute=True)).within_group(gateway_calls.c.latency_ms)


def _errors() -> sa.ColumnElement[int]:
    # A sum of a case, not count(*) FILTER (WHERE ...), which SQL Server does not have.
    return sa.func.sum(sa.case((gateway_calls.c.outcome == "error", 1), else_=0))


def _ran_since(module_ids: list[str], since: str, tenant_id: str, team_ids: list[str]) -> list[sa.ColumnElement[bool]]:
    return [
        gateway_calls.c.tenant_id == tenant_id,
        gateway_calls.c.team_id.in_(team_ids),
        gateway_calls.c.module_id.in_(module_ids),
        gateway_calls.c.created_at >= since,
        gateway_calls.c.outcome.in_(RAN),
    ]


async def traffic(
    conn: AsyncConnection, module_ids: list[str], since: str, *, tenant_id: str, team_ids: list[str]
) -> dict[tuple[str, str | None], CallStats]:
    """Calls, errors and p95 latency since `since`, per (module, operation) and per module (operation None), in one
    aggregate: GROUPING SETS gives the module's p95 over all its calls, which the operations' p95s cannot."""
    if not module_ids:
        return {}
    c = gateway_calls.c
    ran = _ran_since(module_ids, since, tenant_id, team_ids)
    if dialect_of(conn) == "mssql":
        return await _traffic_mssql(conn, ran)
    q = (
        sa.select(
            c.module_id,
            c.tool,
            sa.func.grouping(c.tool).label("whole"),
            sa.func.count().label("calls"),
            _errors().label("errors"),
            _p95().label("p95"),
        )
        .where(*ran)
        .group_by(sa.func.grouping_sets(sa.tuple_(c.module_id, c.tool), sa.tuple_(c.module_id)))
    )
    found = (await conn.execute(q)).mappings().all()
    return {
        (r["module_id"], None if r["whole"] else r["tool"]): CallStats(
            calls=int(r["calls"]), errors=int(r["errors"]), p95_ms=round(r["p95"] or 0)
        )
        for r in found
    }


async def _traffic_mssql(
    conn: AsyncConnection, ran: list[sa.ColumnElement[bool]]
) -> dict[tuple[str, str | None], CallStats]:
    """`traffic` on SQL Server, where percentile_cont is a window function and not an aggregate: each operation's row
    carries its own figures and its module's, over the two partitions, in one statement."""
    c = gateway_calls.c
    by_op, by_module = [c.module_id, c.tool], [c.module_id]
    q = (
        sa.select(
            c.module_id,
            c.tool,
            sa.func.count().over(partition_by=by_op).label("calls"),
            _errors().over(partition_by=by_op).label("errors"),
            _p95().over(partition_by=by_op).label("p95"),
            sa.func.count().over(partition_by=by_module).label("module_calls"),
            _errors().over(partition_by=by_module).label("module_errors"),
            _p95().over(partition_by=by_module).label("module_p95"),
        )
        .where(*ran)
        .distinct()
    )
    out: dict[tuple[str, str | None], CallStats] = {}
    for r in (await conn.execute(q)).mappings().all():
        out[(r["module_id"], r["tool"])] = CallStats(
            calls=int(r["calls"]), errors=int(r["errors"]), p95_ms=round(r["p95"] or 0)
        )
        out[(r["module_id"], None)] = CallStats(
            calls=int(r["module_calls"]), errors=int(r["module_errors"]), p95_ms=round(r["module_p95"] or 0)
        )
    return out


async def daily(
    conn: AsyncConnection, module_id: str, since: str, *, tenant_id: str, team_ids: list[str]
) -> dict[str, DayStats]:
    """Per UTC day since `since`: calls, errors and p95 latency. created_at is ISO text, so its first ten characters
    are the day."""
    c = gateway_calls.c
    day = sa.func.left(c.created_at, 10)
    ran = _ran_since([module_id], since, tenant_id, team_ids)
    if dialect_of(conn) == "mssql":
        # percentile_cont is a window function there: one row per day over the day's partition.
        q = (
            sa.select(
                day.label("day"),
                sa.func.count().over(partition_by=day).label("calls"),
                _errors().over(partition_by=day).label("errors"),
                _p95().over(partition_by=day).label("p95"),
            )
            .where(*ran)
            .distinct()
        )
    else:
        q = (
            sa.select(day.label("day"), sa.func.count().label("calls"), _errors().label("errors"), _p95().label("p95"))
            .where(*ran)
            .group_by(day)
        )
    found = (await conn.execute(q)).mappings().all()
    return {
        r["day"]: DayStats(count=int(r["calls"]), errors=int(r["errors"]), p95_ms=round(r["p95"] or 0)) for r in found
    }
