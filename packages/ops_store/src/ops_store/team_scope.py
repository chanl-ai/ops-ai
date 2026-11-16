"""The team a request reads as, and the one where-clause every read of a team-owned table carries.

  set_acting_team(principal.team_id)            # once per request, from the verified caller's X-Team-Id
  sa.select(agents).where(team_visible(agents))  # the caller's team's rows and workspace-level (null team) rows
  sa.select(agents).where(any_team(agents, "the owning team a refusal is decided on"))

A table is team-owned when its `info` carries `ops_store.schema.TEAM_OWNED` (or `team_owned("team")`); a table whose
rows belong to a team-owned parent carries `team_owned_via(parent, column)` and is read through the parent's team.
With no acting team (the dev header caller, a service acting for the whole tenant, a loop between requests) the
clause is true: those callers read every team, and their routes say so. Another team's record is then absent from
every read, so its route answers 404. Inside `isolation.install_wide`, which has no team and no tenant, it raises.

`any_team` is the one way to read every team's rows while a team is set; its reason is required and the guard test
lists where it is used.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol

import sqlalchemy as sa

from .schema import TEAM_KEY, TEAM_VIA_KEY


class InstallScopeError(RuntimeError):
    """A statement or filter inside an install-wide block (`isolation.install_wide`) that could reach a tenant's
    rows: a table not marked `system(...)`, raw SQL, or a team filter, which has no team to name there."""


_acting: ContextVar[str | None] = ContextVar("ops_acting_team", default=None)
# Set for an install-wide block: no team, which is not every team, so `team_visible` refuses there.
_install: ContextVar[bool] = ContextVar("ops_install_scope", default=False)


class Caller(Protocol):
    """What a verified caller (`ops_identity.Principal`) says about its team."""

    @property
    def kind(self) -> str: ...
    @property
    def team_id(self) -> str | None: ...


def acting_team_of(caller: Caller, *, services: bool = True) -> str | None:
    """The team a caller reads as: the X-Team-Id its token was checked against. None (every team) for a service token
    when `services` is false: a service that acts for the whole tenant names its team on each call instead."""
    if caller.kind == "service" and not services:
        return None
    return caller.team_id or None


def set_acting_team(team_id: str | None) -> None:
    """For a request: set by the service's auth dependency, so it lasts the request."""
    _acting.set(team_id or None)


def acting_team() -> str | None:
    return _acting.get()


@contextmanager
def acting_as(team_id: str | None, *, install: bool = False) -> Generator[None]:
    """For a task that works one team's item (a run's pass) and for tests; `install` only for `install_wide`."""
    token = _acting.set(team_id or None)
    wide = _install.set(install)
    try:
        yield
    finally:
        _install.reset(wide)
        _acting.reset(token)


def team_visible(table: sa.Table) -> sa.ColumnElement[bool]:
    """The acting team's rows of `table` and its workspace-level rows (null team); every row with no acting team. An
    install-wide block has no team and no tenant, so it raises there rather than read every tenant's rows of a table
    with no row policy."""
    if _install.get():
        raise InstallScopeError(f"refused: {table.name} is filtered by team inside an install-wide block")
    team = acting_team()
    if team is None:
        return sa.true()
    via = table.info.get(TEAM_VIA_KEY)
    if via is not None:
        parent_name, column = via
        parent = table.metadata.tables[str(parent_name)]
        child: sa.ColumnElement[str] = table.c[str(column)]
        key = list(parent.primary_key.columns)
        if key and key[0].name == "tenant_id" and "tenant_id" in table.c:
            # Two tenants may hold one parent id, so the id alone could match a visible parent of another tenant.
            # A correlated EXISTS, since SQL Server has no tuple IN.
            return sa.exists().where(
                parent.c.tenant_id == table.c.tenant_id, parent.c.id == child, team_visible(parent)
            )
        return child.in_(sa.select(parent.c.id).where(team_visible(parent)))
    column_name = table.info.get(TEAM_KEY)
    if column_name is None:
        raise ValueError(f"{table.name} is not marked TEAM_OWNED or team_owned_via")
    owner: sa.Column[str] = table.c[str(column_name)]
    # A NOT NULL team column holds no workspace-level rows, and the bare equality lets the planner seek on an index
    # leading (tenant_id, team_id, ...); the OR with IS NULL would not.
    return owner == team if not owner.nullable else sa.or_(owner == team, owner.is_(None))


def any_team(table: sa.Table, reason: str) -> sa.ColumnElement[bool]:
    """Every team's rows of `table`, whoever is acting: for a lookup that decides a refusal by the owning team, never
    to show a record. `reason` is required."""
    if not reason.strip():
        raise ValueError(f"any_team({table.name}) needs a reason")
    return sa.true()
