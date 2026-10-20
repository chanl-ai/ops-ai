"""The one isolation context every transaction carries (c-409; design: c-408 spec section 1).

  isolation.enter_caller(principal, dev=...)      # once per request, by ops_identity, from the verified caller
  async with isolation.isolated_tx(engine, role=ROLE) as conn: ...   # every read and write of an isolated table
  with isolation.tenant_wide(SEED, tenant_id=t): ...                # every team of one tenant, for a named reason
  async with isolation.system_tx(engine, CLAIM, role=SYSTEM): ...   # past the tenant, for a named reason

The context is (tenant, one active team, scope, kind, reason). The tenant comes from the verified token or key and the
team from X-Team-Id checked against it (`ops_identity`), never from a body, header or path. `isolated_tx` writes the
three values into the transaction: `app.tenant_id`, `app.team_id` and `app.scope` with `set_config(..., true)` on
PostgreSQL, which end with the transaction, and SESSION_CONTEXT on SQL Server, which outlives it and is cleared when
it ends however it ends. With no context it raises `NoTenantError` before opening a connection, so a path that forgot
its caller fails instead of reading anything.

Scope is `team` for every person, API key and service token that names a team. Only two calls widen it, each with a
reason that is a named constant of the calling service and logged as `isolation.widen`: `tenant_wide` (every team of
one tenant: the dev header caller, a service token with no team, a loop or seed that acts for the whole tenant) and
`system_tx` (past the tenant, as a role whose grants limit what it reads). `packages/ops_store/tests/
test_isolation_sites.py` lists every call site of both, and of `enter` and `scope`, by reason.

The team is also c-407's acting team (`team_scope`), so the query filter and the database read one value: a team
scope acts as its team, and a wider scope as none (every team of the tenant).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal, Protocol

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_service_kit.logging import get_logger

from . import dialect
from .team_scope import acting_as, set_acting_team

log = get_logger(__name__)

Scope = Literal["team", "tenant", "system"]
# The transaction settings policies read: PostgreSQL custom settings and SQL Server SESSION_CONTEXT keys.
SETTINGS = {"tenant_id": "app.tenant_id", "team_id": "app.team_id", "scope": "app.scope"}
# The reason the dev header caller (dev mode only, no roles) acts for every team of its tenant.
DEV = "dev"
# A service token with no team claim acts for the tenant; its reason names the service.
SERVICE = "service"
# The kind of a context no request set: a loop, a seed or a test.
TASK = "task"


class NoTenantError(RuntimeError):
    """A tenant-scoped statement ran with no isolation context set."""


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


@asynccontextmanager
async def isolated_tx(engine: AsyncEngine, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """One transaction carrying the current context, as `role` on PostgreSQL (a role row-level security applies to),
    with SQL Server's session context cleared when it ends however it ends."""
    ctx = current()
    async with engine.connect() as conn:
        try:
            async with conn.begin():
                await enter_transaction(conn, ctx, role=role)
                yield conn
        finally:
            await leave_transaction(conn)
            if conn.in_transaction():
                await conn.commit()


@asynccontextmanager
async def system_tx(engine: AsyncEngine, reason: str, *, role: str | None = None) -> AsyncGenerator[AsyncConnection]:
    """One transaction past the tenant, as `role` (a BYPASSRLS role on PostgreSQL, an impersonated user on SQL Server,
    whose grants limit what it reads), for work claimed before its tenant is known. Logged with `reason`."""
    _need(reason, "system_tx")
    base = _ctx.get()
    log.info(
        "isolation.widen",
        reason=reason,
        scope="system",
        tenant=base.tenant_id if base else "-",
        caller=base.kind if base else TASK,
    )
    async with dialect.system_tx(engine, role=role) as conn:
        yield conn


async def enter_transaction(conn: AsyncConnection, ctx: Isolation, *, role: str | None = None) -> None:
    values = {"tenant_id": ctx.tenant_id, "team_id": ctx.team_id or "", "scope": ctx.scope}
    match dialect.dialect_of(conn):
        case "postgresql":
            if role:
                quoted = postgresql.dialect().identifier_preparer.quote(role)
                await conn.execute(sa.text(f"SET LOCAL ROLE {quoted}"))
            await conn.execute(
                sa.select(*(sa.func.set_config(SETTINGS[k], v, True) for k, v in values.items())),
            )
        case "mssql":
            for key, value in values.items():
                await conn.execute(_MS_SET, {"k": key, "v": value})
        case _:
            return


async def leave_transaction(conn: AsyncConnection) -> None:
    if dialect.dialect_of(conn) == "mssql":
        for key in SETTINGS:
            await conn.execute(_MS_SET, {"k": key, "v": None})


_MS_SET = sa.text("EXEC sp_set_session_context @key = :k, @value = :v")


def _need(reason: str, what: str) -> None:
    if not reason.strip():
        raise ValueError(f"{what} needs a reason")


def _widened(tenant_id: str, kind: str, reason: str, base: Isolation | None) -> Isolation:
    _need(reason, "tenant_wide")
    if not tenant_id:
        raise NoTenantError(f"tenant_wide({reason!r}) has no tenant")
    log.info(
        "isolation.widen",
        reason=reason,
        scope="tenant",
        tenant=tenant_id,
        caller=kind,
        team_before=base.team_id if base and base.team_id else "-",
    )
    return Isolation(tenant_id, None, "tenant", kind, reason)


def _widen_request(tenant_id: str, kind: str, reason: str) -> Isolation:
    found = _widened(tenant_id, kind, reason, None)
    _ctx.set(found)
    set_acting_team(None)
    return found


__all__ = [
    "DEV",
    "SERVICE",
    "TASK",
    "Isolation",
    "NoTenantError",
    "current",
    "enter",
    "enter_caller",
    "isolated_tx",
    "scope",
    "system_tx",
    "team",
    "tenant",
    "tenant_wide",
]
