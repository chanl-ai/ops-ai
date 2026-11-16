"""The base every service's store class extends: how a store reaches a transaction, and nothing about any table.

  class Aliases(Store):
      role = ROLE                                        # the PostgreSQL role its transactions run as

      async def claim_name(self, conn: AsyncConnection, team: str, name: str) -> bool:
          try:
              async with self.attempt(conn):             # a savepoint: the request's transaction survives the refusal
                  await conn.execute(sa.insert(aliases).values(team_id=team, name=name))
          except IntegrityError:
              return False
          return True

  async with aliases.tx() as conn: ...                   # the request's one transaction, or its own outside a request
  async with providers.install_tx(PROVIDERS, tables=(providers_t,)) as conn: ...  # no tenant: these system tables only
  async with readings.system_tx(RECOVER_PENDING) as conn: ...  # every tenant's rows, as the store's system role

A store never calls `engine.begin()` or `engine.connect()`: that is a second connection beside the request's, as the
database's owner, with no caller on it (`tests/test_isolation_sites.py` lists the sites still to move).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from . import isolation
from .schema import TEAM_KEY
from .team_scope import any_team


class Store:
    role: ClassVar[str | None] = None
    # The role `system_tx` runs as: BYPASSRLS on PostgreSQL, the user the read predicates pass on SQL Server.
    system_role: ClassVar[str | None] = None

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        return isolation.isolated_tx(self.engine, role=self.role)

    @asynccontextmanager
    async def install_tx(self, reason: str, *, tables: Iterable[sa.Table]) -> AsyncGenerator[AsyncConnection]:
        """`tx()` with no tenant, for the install's own tables (marked `system(...)`), from a path that may carry no
        caller: a route that authenticates by a model key, a seed, a loop. Inside a request it is the request's
        connection with its scope set for the block and restored after; a tenant table shows it no row and refuses
        its writes (`isolation.install_wide`). `reason` is a named constant, listed in test_isolation_sites.py; `tables`
        are the system tables the block touches, and nothing else runs in it."""
        with isolation.install_wide(reason, tables=tables):
            async with self.tx() as conn:
                yield conn

    def system_tx(self, reason: str) -> AbstractAsyncContextManager[AsyncConnection]:
        """One transaction past the tenant, as `system_role`, whose grants limit what it reads: for work listed before
        its tenant is known (a restart's queued reads), each item then done in its own tenant and team. Its own
        connection, never the request's. `reason` is a named constant, listed in test_isolation_sites.py."""
        return isolation.system_tx(self.engine, reason, role=self.system_role)

    def attempt(self, conn: AsyncConnection) -> AbstractAsyncContextManager[None]:
        """A savepoint around a statement that may fail and be caught, so the request's connection stays usable."""
        return isolation.attempt(conn)

    async def owner_teams(
        self, conn: AsyncConnection | None, table: sa.Table, ids: set[str], reason: str
    ) -> dict[str, str]:
        """The owning team of each id in one query, for deciding a refusal; never for showing the rows. A row with no
        team is left out. The read is tenant-wide for `reason`, since a team's transaction cannot see another team's
        rows: on `conn` with its scope widened for this one statement, then restored; with no `conn`, in `tx()`."""
        if not ids:
            return {}
        column = table.info.get(TEAM_KEY)
        if column is None:
            raise ValueError(f"{table.name} is not marked TEAM_OWNED")
        q = sa.select(table.c.id, table.c[str(column)]).where(table.c.id.in_(sorted(ids)), any_team(table, reason))
        if conn is None:
            with isolation.tenant_wide(reason):
                async with self.tx() as own:
                    found = (await own.execute(q)).all()
        else:
            async with isolation.tenant_wide_on(conn, reason) as wide:
                found = (await wide.execute(q)).all()
        return {str(i): str(team) for i, team in found if team}


__all__ = ["Store"]
