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
import re
from collections.abc import AsyncGenerator, Generator, Iterable, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import ExceptionContext
from sqlalchemy.exc import DBAPIError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncTransaction
from sqlalchemy.sql import operators, visitors
from sqlalchemy.sql.elements import CollationClause, Extract, quoted_name
from sqlalchemy.sql.functions import FunctionElement
from sqlalchemy.sql.selectable import TableValuedAlias

from ops_service_kit.logging import add_context, get_logger
from ops_service_kit.request_timing import note_caller

from . import dialect
from .schema import SYSTEM_KEY
from .team_scope import InstallScopeError, acting_as, acting_team, set_acting_team

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
    # The tables an install-wide block declared it touches; None for one that declared none yet.
    tables: frozenset[str] | None = None


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
def install_wide(reason: str, *, tables: Iterable[sa.Table] | None = None) -> Generator[Isolation]:
    """No tenant for a block, logged with `reason`: statements on the install's own tables (marked `system(...)`) from
    a path that may have no caller (a route that authenticates by a model key, a seed, a loop). Inside a request it
    runs on the request's connection. Every statement on a connection in this scope is checked before it is sent
    (`_refuse_outside_install`): one with a table or column of a table not marked `system(...)`, SQL text, or a
    function not listed in `INSTALL_FUNCTIONS` raises `InstallScopeError`, whatever the login and whether or not the
    table has a row policy. `tenant()` and `team_visible` raise inside. `tables` are the only ones the block may touch,
    each marked `system(...)`; a statement reaching any other, a caller's statement passed in included, is refused.
    A block that declares none is counted in `tests/isolation_sites/install/`, a list that only shrinks."""
    _need(reason, "install_wide")
    declared = None if tables is None else _declared(tables)
    base = _ctx.get()
    _log_widen(base.kind if base else TASK, reason=reason, scope="install", tenant="-")
    token = _ctx.set(Isolation("", None, "install", base.kind if base else TASK, reason, declared))
    try:
        with acting_as(None, install=True):
            yield _ctx.get()  # pyright: ignore[reportReturnType]
    finally:
        _ctx.reset(token)


def _declared(tables: Iterable[sa.Table]) -> frozenset[str]:
    names: set[str] = set()
    for table in tables:
        if not table.info.get(SYSTEM_KEY):
            raise InstallScopeError(f"refused: {table.name} is not marked system(...) and cannot be declared")
        names.add(table.name)
    if not names:
        raise ValueError("an install-wide block declares at least one table")
    return frozenset(names)


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

# What a connection's settings say: the context's tenant, team and scope, the PostgreSQL role, and the tables an
# install-wide block declared (checked here, not by the database, so a change of them alone costs no statement).
_Carried = tuple[str, str | None, str, str | None, frozenset[str] | None]


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
    try:
        if not conn.invalidated:  # an invalidated connection's info raises; its DBAPI connection is discarded anyway
            conn.info.pop(_STATE, None)
        if tx is None:
            return  # BEGIN failed after the connection was taken: it goes back to the pool below.
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
        # A statement cancelled mid-flight leaves the transaction unusable: the clear raises PendingRollbackError (an
        # InvalidRequestError), and the rollback below is what makes the connection usable again.
        with suppress(DBAPIError, InvalidRequestError):
            await leave_transaction(conn)
            cleared = True
        await tx.rollback()
    # An invalidated connection (a statement cancelled mid-flight) is discarded with its session context, and touching
    # it again would reconnect outside the driver's event loop bridge.
    if not cleared and not conn.invalidated:
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
    _guard(engine)
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
    want: _Carried = (ctx.tenant_id, ctx.team_id, ctx.scope, role, ctx.tables)
    before = state.carried
    if before is None or before[:4] != want[:4]:
        await enter_transaction(conn, ctx, role=role, reset_role=before is not None and before[3] is not None)
    elif before != want:
        _mark(conn, ctx)
    state.carried = want
    state.depth += 1
    try:
        yield conn
    finally:
        state.depth -= 1
        # None when a block inside this one failed its own restore.
        now = cast(_Carried | None, state.carried)
        if state.depth and before is not None and now != before:
            # The block around this one reads on with the settings it entered with. A restore that fails has failed
            # the request (`_on_error`), so nothing reads on with the wrong scope.
            state.carried = None
            # A cancelled statement leaves the transaction unusable, and the restore's PendingRollbackError would
            # replace the cancellation; the request rolls back either way, since carried stays None.
            with suppress(DBAPIError, InvalidRequestError):
                tenant_id, team_id, scope_, role_, tables_ = before
                back = Isolation(tenant_id, team_id, scope_, ctx.kind, tables=tables_)  # pyright: ignore[reportArgumentType]
                if now is not None and now[:4] == before[:4]:
                    _mark(conn, back)
                else:
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
    # The mechanism's own statement (set_config, a function no install block may call) is not an install block's: the
    # mark goes first. A statement that fails here fails its transaction, so nothing runs on unmarked.
    conn.info.pop(_INSTALL, None)
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
            pass
    # Marked after the statement that set it: the connection now carries the scope its statements are checked by.
    _mark(conn, ctx)


def _mark(conn: AsyncConnection, ctx: Isolation) -> None:
    """What the guard checks this connection's statements by: an install scope's declared tables, or every system
    table for a block that declared none; nothing outside install scope."""
    if ctx.scope == "install":
        conn.info[_INSTALL] = ctx.tables if ctx.tables is not None else _UNDECLARED
    else:
        conn.info.pop(_INSTALL, None)


async def leave_transaction(conn: AsyncConnection) -> None:
    conn.info.pop(_INSTALL, None)
    if dialect.dialect_of(conn) == "mssql":
        await conn.execute(_MS_SET, dict.fromkeys(SETTINGS))


# Install-wide statements -------------------------------------------------------------------------------------------

# A connection's info key while it carries install scope. It lives on the pooled connection, so it is also cleared
# when the connection goes back to the pool, however its block ended.
_INSTALL = "ops_install_scope"
# Its value for a block that declared no tables: every table marked system(...) is reachable.
_UNDECLARED = True


def _guard(engine: AsyncEngine) -> None:
    """Checks every statement on `engine`'s connections that carry install scope, registered once per engine before
    its first isolated transaction opens a connection."""
    sync = engine.sync_engine
    if not event.contains(sync, "before_execute", _refuse_outside_install):
        event.listen(sync, "before_execute", _refuse_outside_install)
        # SQL for the driver (`exec_driver_sql`) skips before_execute; it reaches the cursor uncompiled.
        event.listen(sync, "before_cursor_execute", _refuse_driver_sql)
        event.listen(sync, "checkin", _forget_install)


def _forget_install(_dbapi_conn: object, record: Any) -> None:
    record.info.pop(_INSTALL, None)


# A literal column that cannot name a table: count(*)'s star, a number, a quoted string or a bare name. Anything else
# (a parenthesised subquery) is raw SQL.
_BARE = re.compile(r"\*|-?\d+(\.\d+)?|'[^']*'|[A-Za-z_][A-Za-z0-9_]*")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The database functions a statement in install scope may call, by name: the ones today's install statements use
# (a count, a fallback, a maximum), which read only their arguments. Any other function may read any table (or a view
# over one), so it is refused, as is a schema-qualified name or a function used as a table. The database's clock
# (`dialect.db_now`, `db_epoch`, `db_after`) runs too.
INSTALL_FUNCTIONS = frozenset({"coalesce", "count", "max"})
_CLOCK = (dialect.db_now, dialect.db_epoch, dialect.db_after)
# The statements an install-wide block runs: a DDL element or anything else is refused.
_STATEMENTS = (sa.Select, sa.CompoundSelect, sa.Insert, sa.Update, sa.Delete)
# Text a statement carries beside its tree, which the walk below does not reach: rendered as written.
_TEXT_PARTS = ("_prefixes", "_suffixes", "_statement_hints")


def _refuse_driver_sql(conn: sa.Connection, _cursor: Any, _sql: str, _params: Any, context: Any, _many: bool) -> None:
    if conn.info.get(_INSTALL) and context.compiled is None:
        raise InstallScopeError("refused: SQL for the driver inside an install-wide block names no table to check")


def _refuse_outside_install(conn: sa.Connection, statement: Any, *_: Any) -> None:
    """Raises before a statement on a connection in install scope is sent unless every table it reaches is marked
    `system(...)`. Every column is judged by its table, so a value, a RETURNING or a join condition naming another
    table is refused even where the statement's tree does not hold that table. Raw SQL (a text clause, a literal
    column, a custom operator, a prefix, suffix or hint other than the dialect's lock hints, a collation or EXTRACT
    field, an unquoted name, a string for the driver) names no table the check can read, so it is refused rather than
    parsed; the mechanism's own context statements are the exceptions. A function runs only when it is listed
    (`INSTALL_FUNCTIONS`) or is the database's clock. Each statement is checked as written, so a cached compile does
    not skip it."""
    if not conn.info.get(_INSTALL) or statement is _MS_SET:
        return
    kind: type[object] = type(cast(object, statement))
    if not issubclass(kind, _STATEMENTS):
        raise InstallScopeError(f"refused: a {kind.__name__} inside an install-wide block")
    found: object = conn.info[_INSTALL]
    declared = cast(frozenset[str], found) if isinstance(found, frozenset) else None
    problem = next(_install_problems(statement, declared), None)
    if problem is not None:
        raise InstallScopeError(f"refused: {problem} inside an install-wide block")


def _install_problems(statement: sa.ClauseElement, declared: frozenset[str] | None) -> Iterator[str]:
    """Each part of `statement` an install-wide block may not send. A column's table is walked too, since a column
    can stand in a statement whose tree never holds its table (an UPDATE's value, a RETURNING)."""
    seen: set[int] = set()
    todo: list[sa.ClauseElement] = [statement]
    while todo:
        for found in visitors.iterate(todo.pop()):
            e: object = found
            if id(e) in seen:
                continue
            seen.add(id(e))
            table: object = getattr(e, "table", None)
            if (
                issubclass(type(e), sa.ColumnClause)
                and issubclass(type(table), sa.FromClause)
                and id(table) not in seen
            ):
                todo.append(cast(sa.ClauseElement, table))
            yield from _part_problems(e, declared)


def _part_problems(e: object, declared: frozenset[str] | None) -> Iterator[str]:
    """What is wrong with one element of an install-wide statement, read by attribute: the element classes differ.
    Judged by its class (`issubclass`), so the attributes read first stay one type each."""
    kind = type(e)
    name: object = getattr(e, "name", None)
    marked = issubclass(kind, sa.Table) and bool(cast(sa.Table, e).info.get(SYSTEM_KEY))
    text: object = getattr(e, "field", None) if issubclass(kind, Extract) else getattr(e, "collation", None)
    hints: dict[object, str] = getattr(e, "_hints", None) or {}
    ops: list[object] = [getattr(e, "operator", None), getattr(e, "modifier", None)]
    beside: list[object] = [getattr(e, part, ()) for part in _TEXT_PARTS]
    packages: object = getattr(e, "packagenames", ())
    literal: object = getattr(e, "is_literal", False)
    if issubclass(kind, sa.TextClause) or (
        issubclass(kind, sa.ColumnClause) and literal and not _BARE.fullmatch(str(name))
    ):
        yield "raw SQL (a text clause or a literal column)"
    if issubclass(kind, sa.TableClause) and not marked:
        yield f"{name} is not marked system(...); an install-wide block reaches only the install's own tables"
    elif marked and declared is not None and str(name) not in declared:
        yield f"{name} is not among the tables this block declared ({', '.join(sorted(declared))})"
    if isinstance(name, quoted_name) and name.quote is False and not _BARE.fullmatch(str(name)):
        yield f"an unquoted name {str(name)!r}"
    if any(isinstance(op, operators.custom_op) for op in ops):
        yield "raw SQL (a custom operator)"
    if issubclass(kind, Extract | CollationClause) and not _NAME.fullmatch(str(text)):
        yield f"raw SQL (an EXTRACT field or collation {text!r})"
    if issubclass(kind, TableValuedAlias):
        yield "a function used as a table"
    if issubclass(kind, FunctionElement) and not issubclass(kind, _CLOCK):
        fn = str(name or kind.__name__).lower()
        if packages or fn not in INSTALL_FUNCTIONS:
            yield f"the function {fn} (listed: {', '.join(sorted(INSTALL_FUNCTIONS))})"
    if any(beside):
        yield "raw SQL (a prefix, suffix or statement hint)"
    if any(hint not in dialect.LOCK_HINTS for hint in hints.values()):
        yield "raw SQL (a table hint other than the dialect's lock hints)"


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
    "InstallScopeError",
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
