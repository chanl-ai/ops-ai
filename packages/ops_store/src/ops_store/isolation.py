"""The one isolation context every transaction carries.

  isolation.enter_caller(principal, dev=...)      # once per request, by ops_identity, from the verified caller
  async with isolation.isolated_tx(engine, role=ROLE) as conn: ...   # every read and write of an isolated table
  with isolation.tenant_wide(SEED, tenant_id=t): ...                # every team of one tenant, for a named reason
  async with isolation.system_tx(engine, CLAIM, role=SYSTEM): ...   # past the tenant, for a named reason
  async with isolation.request_transaction(): ...                   # one request: every isolated_tx inside shares one

The context is (tenant, one active team, scope, kind, reason). The tenant comes from the verified token or key and the
team from X-Team-Id checked against it (`ops_identity`), never from a body, header or path. `isolated_tx` writes the
three values into the transaction: `app.tenant_id`, `app.team_id` and `app.scope` with `set_config(..., true)` on
PostgreSQL, which end with the transaction, and SESSION_CONTEXT on SQL Server, which outlives it and is cleared when
it ends however it ends. With no context it raises `NoTenantError` before opening a connection, so a path that forgot
its caller fails instead of reading anything.

Scope is `team` for every person, API key and service token that names a team. Only two calls widen it, each with a
reason that is a named constant of the calling service and logged as `isolation.widen`: `tenant_wide` (every team of
one tenant: the dev header caller, a service token with no team, a loop or seed that acts for the whole tenant) and
`system_tx` (past the tenant, as a role whose grants limit what it reads); `install_wide` is no tenant, for
system(...) tables. `packages/ops_store/tests/test_isolation_sites.py` lists every call site of the three, and of
`enter` and `scope`.

The team is also the acting team (`team_scope`), so the query filter and the database read one value: a team
scope acts as its team, and a wider scope as none (every team of the tenant).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction

from ops_service_kit.logging import add_context, get_logger
from ops_service_kit.request_timing import note_caller

from . import dialect
from .team_scope import acting_as, acting_team, set_acting_team

log = get_logger(__name__)

Scope = Literal["team", "tenant", "system", "install"]
# The transaction settings policies read: PostgreSQL custom settings and SQL Server SESSION_CONTEXT keys.
SETTINGS = {"tenant_id": "app.tenant_id", "team_id": "app.team_id", "scope": "app.scope"}
# The reason the dev header caller (dev mode only, no roles) acts for every team of its tenant.
DEV = "dev"
# A service token with no team claim acts for the tenant; its reason names the service.
SERVICE = "service"
# The kind of a context no request set: a loop, a seed or a test.
TASK = "task"
# What an install-wide transaction carries as its tenant on PostgreSQL, which cannot unset a setting: longer than any
# tenant column (String(64)) holds, so a tenant policy matches no row and refuses every write. SQL Server gets NULL.
_NO_TENANT = "-" * 65


class NoTenantError(RuntimeError):
    """A tenant-scoped statement ran with no isolation context set."""


class RequestTransactionFailed(RuntimeError):
    """A database error left an `isolated_tx` block of the request's transaction outside `attempt`, so nothing after
    it can commit: the statement that may fail belongs inside `Store.attempt(conn)`."""


@dataclass(frozen=True)
class Isolation:
    tenant_id: str
    team_id: str | None
    scope: Scope
    # Who acts: a principal's kind (person, api_key, service), or widget, task, test.
    kind: str
    # Why a wider scope than `team` is in force; None for a team scope.
    reason: str | None = None


class Caller(Protocol):
    """What a verified caller (`ops_identity.Principal`) says about itself."""

    @property
    def kind(self) -> str: ...
    @property
    def sub(self) -> str: ...
    @property
    def tenant_id(self) -> str: ...
    @property
    def team_id(self) -> str | None: ...
    @property
    def auth_method(self) -> str: ...
    @property
    def roles(self) -> dict[str, str]: ...


_ctx: ContextVar[Isolation | None] = ContextVar("ops_isolation", default=None)


def current() -> Isolation:
    found = _ctx.get()
    if found is None or not found.tenant_id:
        raise NoTenantError("no tenant is set for this statement; a request sets it in ops_identity")
    return found


def log_ids() -> dict[str, str | None]:
    """The tenant and team every log line carries (`ops_service_kit.logging`): the isolation context's, and the acting
    team when no context names one."""
    found = _ctx.get()
    return {
        "tenant_id": found.tenant_id if found else None,
        "team_id": (found.team_id if found else None) or acting_team(),
    }


add_context(log_ids)


def tenant() -> str:
    return current().tenant_id


def team() -> str | None:
    """The active team; None in a tenant-wide or system scope."""
    found = _ctx.get()
    return found.team_id if found is not None else None


def enter_caller(caller: Caller, *, dev: bool) -> Isolation:
    """For a request, from its verified caller; lasts the request (a dependency's context is the route's). `dev` is
    whether the resolving Identity was built for dev mode: only there is a person with no roles the dev header caller,
    since platform-service marks every session `auth_method` dev."""
    if dev and caller.kind == "person" and caller.auth_method == "dev" and not caller.roles:
        return _widen_request(caller.tenant_id, caller.kind, DEV)
    if caller.kind == "service" and not caller.team_id:
        return _widen_request(caller.tenant_id, caller.kind, f"{SERVICE}:{caller.sub.removeprefix('service:')}")
    return enter(caller.tenant_id, caller.team_id, kind=caller.kind)


def enter(tenant_id: str, team_id: str | None, *, kind: str) -> Isolation:
    """A team scope for the rest of the current task: a request's verified caller, a credential a route checks itself
    (a widget's mint key or session), or a worker pass entering its run's team."""
    if not tenant_id:
        raise NoTenantError("a context needs a tenant")
    found = Isolation(tenant_id, team_id or None, "team", kind)
    _ctx.set(found)
    set_acting_team(found.team_id)
    note_caller(found.tenant_id, found.team_id)
    return found


@contextmanager
def scope(tenant_id: str, team_id: str | None) -> Generator[Isolation]:
    """A team scope for a block: a task working one team's item, or a decision recorded as the owning team. Inside a
    request it keeps the request's caller kind."""
    if not tenant_id:
        raise NoTenantError("a context needs a tenant")
    base = _ctx.get()
    found = Isolation(tenant_id, team_id or None, "team", base.kind if base else TASK)
    token = _ctx.set(found)
    try:
        with acting_as(found.team_id):
            yield found
    finally:
        _ctx.reset(token)


@contextmanager
def install_wide(reason: str) -> Generator[Isolation]:
    """No tenant for a block, logged with `reason`: statements on the install's own tables (marked `system(...)`) from
    a path that may have no caller (a route that authenticates by a model key, a seed, a loop). Inside a request it
    runs on the request's connection; a tenant table's policy shows it no row and refuses its writes, for any login
    row-level security applies to (every runtime login; the compose superuser bypasses it). `tenant()` raises inside."""
    _need(reason, "install_wide")
    base = _ctx.get()
    _log_widen(base.kind if base else TASK, reason=reason, scope="install", tenant="-")
    token = _ctx.set(Isolation("", None, "install", base.kind if base else TASK, reason))
    try:
        with acting_as(None):
            yield _ctx.get()  # pyright: ignore[reportReturnType]
    finally:
        _ctx.reset(token)


def _in_force() -> Isolation:
    """The context a transaction carries: the current one, which names a tenant unless `install_wide` set it."""
    found = _ctx.get()
    return found if found is not None and found.scope == "install" else current()


@contextmanager
def tenant_wide(reason: str, *, tenant_id: str | None = None) -> Generator[Isolation]:
    """Every team of one tenant for a block, logged with `reason`: the current context's tenant, or `tenant_id` for a
    loop or seed that has none (read from a claimed row or the install's settings). Every call site is listed by reason
    in `test_isolation_sites.py`."""
    base = _ctx.get()
    found = _widened(tenant_id or (base.tenant_id if base else ""), base.kind if base else TASK, reason, base)
    token = _ctx.set(found)
    try:
        with acting_as(None):
            yield found
    finally:
        _ctx.reset(token)


# One transaction per request (`request_transaction`, entered by `ops_identity.fastapi.Tx`): the first `isolated_tx`
# of the request's task opens the connection and every later one re-enters it, so a request with twenty reads costs
# one checkout, one BEGIN and one COMMIT, and its writes commit together. The context statement runs again only when
# the role or the scope differs from what the connection carries. Another asyncio task (a gather branch, a created
# task, a stream's generator after the route returned, a loop, a seed) is not the request and opens its own.
# PostgreSQL refuses every statement after a failed one, so a database error that is caught runs inside `attempt`, a
# savepoint; any other database error on the request's connection fails the request's transaction, on both databases,
# wherever it is caught: an engine listener sees every one (`_on_error`), so a route that catches it, or turns it into
# a Conflict, cannot answer as if its writes held.

# What a connection's settings say: the context's tenant, team and scope, and the PostgreSQL role.
_Carried = tuple[str, str | None, str, str | None]


@dataclass
class _Request:
    """One request's transaction. Child tasks copy the ContextVar that holds it, so it names the task it belongs to."""

    task: asyncio.Task[Any] | None
    engine: AsyncEngine | None = None
    conn: AsyncConnection | None = None
    tx: AsyncTransaction | None = None
    carried: _Carried | None = None
    # isolated_tx blocks open now; a block that changed the settings restores them only for a block around it.
    depth: int = 0
    failed: BaseException | None = None
    closed: bool = False


_request: ContextVar[_Request | None] = ContextVar("ops_request_transaction", default=None)


def _request_here(engine: AsyncEngine) -> _Request | None:
    """The request transaction this call joins: the current task's, still open, on this engine."""
    found = _request.get()
    if found is None or found.closed or found.task is not asyncio.current_task():
        return None
    return found if found.engine is None or found.engine is engine else None


@asynccontextmanager
async def request_transaction() -> AsyncGenerator[None]:
    """Held for one request by the Tx dependency. Opens nothing. The first isolated_tx in this asyncio task opens
    the request's connection and begins; every later isolated_tx in the same task re-enters it. Exit clears SQL
    Server's session context, then commits once, or rolls back once on an exception."""
    outer = _request.get()
    if outer is not None and not outer.closed and outer.task is asyncio.current_task():
        yield  # already inside one: the outer block ends it
        return
    state = _Request(asyncio.current_task())
    _request.set(state)
    try:
        yield
    except BaseException:
        await _end(state, commit=False)
        raise
    else:
        failed = state.failed
        await _end(state, commit=failed is None)
        if failed is not None:
            # The route caught the error and answered as if its writes held; they did not.
            raise RequestTransactionFailed("the request's transaction failed and was rolled back") from failed
    finally:
        # Not a token reset: the dependency's exit may run in another context than its entry.
        state.closed = True
        _request.set(outer)


_STATE = "ops_request_transaction"


def _on_error(context: ExceptionContext) -> None:
    """Marks the open request whose connection raised a database error as failed, the first such error only. `attempt`
    clears it when it rolls back to its savepoint."""
    conn = context.connection
    state = conn.info.get(_STATE) if conn is not None else None
    if isinstance(state, _Request) and not state.closed and state.failed is None:
        state.failed = context.sqlalchemy_exception


async def _end(state: _Request, *, commit: bool) -> None:
    conn, tx = state.conn, state.tx
    state.closed = True
    if conn is None:
        return
    conn.sync_connection.info.pop(_STATE, None)  # pyright: ignore[reportOptionalMemberAccess]
    if tx is None:
        # BEGIN failed after the connection was taken: it goes back to the pool, or the request leaks it.
        await conn.close()
        return
    try:
        if commit:
            # Cleared before the commit, so a transaction commits once.
            await leave_transaction(conn)
            await tx.commit()
            return
        await _roll_back(conn, tx)
    finally:
        await conn.close()


async def _roll_back(conn: AsyncConnection, tx: AsyncTransaction) -> None:
    """Rolls back with SQL Server's session context cleared, since the pooled connection must not carry it on. The
    clear runs first, inside the transaction it rolls back: session context is not transactional, so it holds after
    the rollback and the request still counts one transaction. A doomed transaction refuses the clear; then it runs
    after the rollback, in a transaction of its own."""
    cleared = False
    if tx.is_active:
        with suppress(DBAPIError):
            await leave_transaction(conn)
            cleared = True
        await tx.rollback()
    if not cleared:
        await leave_transaction(conn)
        if conn.in_transaction():
            await conn.commit()


@asynccontextmanager
async def isolated_tx(engine: AsyncEngine, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """Inside a request: re-enters the request's connection; a different role or a wider scope re-runs the context
    statement on the same connection and restores it on exit. In another task (gather branch, created task, loop,
    seed, test): its own transaction, as `role` on PostgreSQL (a role row-level security applies to), with SQL
    Server's session context cleared when it ends however it ends. Only system_tx takes a second connection."""
    ctx = _in_force()
    state = _request_here(engine)
    if state is None:
        async with _own_tx(engine, ctx, role) as conn:
            yield conn
        return
    if state.failed is not None:
        raise RequestTransactionFailed("the request's transaction already failed") from state.failed
    if state.conn is None:
        state.engine = engine
        if not event.contains(engine.sync_engine, "handle_error", _on_error):
            event.listen(engine.sync_engine, "handle_error", _on_error)
        state.conn = await engine.connect()
        state.conn.sync_connection.info[_STATE] = state  # pyright: ignore[reportOptionalMemberAccess]
        state.tx = await state.conn.begin()
    conn = state.conn
    want: _Carried = (ctx.tenant_id, ctx.team_id, ctx.scope, role)
    before = state.carried
    if before != want:
        await enter_transaction(conn, ctx, role=role, reset_role=before is not None and before[3] is not None)
        state.carried = want
    state.depth += 1
    try:
        yield conn
    finally:
        state.depth -= 1
        if state.depth and before is not None and state.carried != before:
            # The block around this one reads on with the settings it entered with. A restore that fails has failed
            # the request (`_on_error`), so nothing reads on with the wrong scope.
            state.carried = None
            with suppress(DBAPIError):
                tenant_id, team_id, scope_, role_ = before
                back = Isolation(tenant_id, team_id, scope_, ctx.kind)  # pyright: ignore[reportArgumentType]
                await enter_transaction(conn, back, role=role_, reset_role=role is not None)
                state.carried = before


@asynccontextmanager
async def attempt(conn: AsyncConnection) -> AsyncGenerator[None]:
    """A savepoint around a statement that may fail and be caught, so the transaction stays usable: the failed
    statement is rolled back to the savepoint and the error raised on for the caller to catch."""
    try:
        async with conn.begin_nested():
            yield
    except DBAPIError as e:
        state = _request.get()
        if state is not None and state.conn is conn and state.failed is e:
            # Rolled back to the savepoint, the transaction is good again, even when the statement ran in a store
            # method's own tx() block inside this one.
            state.failed = None
        raise


@asynccontextmanager
async def _own_tx(engine: AsyncEngine, ctx: Isolation, role: str | None) -> AsyncGenerator[AsyncConnection]:
    async with engine.connect() as conn:
        tx = await conn.begin()
        try:
            await enter_transaction(conn, ctx, role=role)
            yield conn
            # Cleared before the commit, so a transaction commits once: a second commit after it cost a round trip on
            # every SQL Server save (slow-tests RCA A3).
            await leave_transaction(conn)
            await tx.commit()
        except BaseException:
            await _roll_back(conn, tx)
            raise


@asynccontextmanager
async def system_tx(engine: AsyncEngine, reason: str, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """One transaction past the tenant, as `role` (a BYPASSRLS role on PostgreSQL, an impersonated user on SQL Server,
    whose grants limit what it reads), for work claimed before its tenant is known. Logged with `reason`."""
    _need(reason, "system_tx")
    base = _ctx.get()
    _log_widen(base.kind if base else TASK, reason=reason, scope="system", tenant=base.tenant_id if base else "-")
    async with dialect.system_tx(engine, role=role) as conn:
        yield conn


async def enter_transaction(
    conn: AsyncConnection, ctx: Isolation, *, role: str | None = None, reset_role: bool = False
) -> None:
    """Writes the context into the transaction. `reset_role` is for a transaction that already runs as a role and
    now needs none: PostgreSQL goes back to the login's own."""
    install = ctx.scope == "install"
    values = {"tenant_id": ctx.tenant_id, "team_id": ctx.team_id or "", "scope": ctx.scope}
    match dialect.dialect_of(conn):
        case "postgresql":
            values["tenant_id"] = _NO_TENANT if install else ctx.tenant_id
            # The role is set by the same statement as the context: set_config('role', ...) is SET LOCAL ROLE, with the
            # same membership check, and a transaction's setup is one round trip.
            as_role = role or ("none" if reset_role else None)
            settings = [*([("role", as_role)] if as_role else []), *((SETTINGS[k], v) for k, v in values.items())]
            await conn.execute(sa.select(*(sa.func.set_config(name, v, True) for name, v in settings)))
        case "mssql":
            await conn.execute(_MS_SET, {**values, "tenant_id": None} if install else values)
        case _:
            return


async def leave_transaction(conn: AsyncConnection) -> None:
    if dialect.dialect_of(conn) == "mssql":
        await conn.execute(_MS_SET, dict.fromkeys(SETTINGS))


# The three keys in one batch, one round trip to set them and one to clear them (slow-tests RCA A3).
_MS_SET = sa.text(" ".join(f"EXEC sp_set_session_context @key = N'{k}', @value = :{k};" for k in SETTINGS))


def _need(reason: str, what: str) -> None:
    if not reason.strip():
        raise ValueError(f"{what} needs a reason")


def _widened(tenant_id: str, kind: str, reason: str, base: Isolation | None) -> Isolation:
    _need(reason, "tenant_wide")
    if not tenant_id:
        raise NoTenantError(f"tenant_wide({reason!r}) has no tenant")
    _log_widen(
        kind,
        reason=reason,
        scope="tenant",
        tenant=tenant_id,
        team_before=base.team_id if base and base.team_id else "-",
    )
    return Isolation(tenant_id, None, "tenant", kind, reason)


def _log_widen(caller: str, **fields: str) -> None:
    """Every widening is logged with its reason. One a request's caller asked for is INFO, the audit trail of who read
    past their team; a loop's (no caller: a relay, a claim, a poll) is DEBUG, since each loop widens on every pass,
    twice a second, and at INFO that buried the request lines and cost a small host its CPU."""
    (log.debug if caller == TASK else log.info)("isolation.widen", caller=caller, **fields)


def _widen_request(tenant_id: str, kind: str, reason: str) -> Isolation:
    found = _widened(tenant_id, kind, reason, None)
    _ctx.set(found)
    note_caller(found.tenant_id, found.team_id)
    set_acting_team(None)
    return found


__all__ = [
    "DEV",
    "SERVICE",
    "TASK",
    "Isolation",
    "NoTenantError",
    "RequestTransactionFailed",
    "attempt",
    "current",
    "enter",
    "enter_caller",
    "install_wide",
    "isolated_tx",
    "request_transaction",
    "scope",
    "system_tx",
    "team",
    "tenant",
    "tenant_wide",
]
