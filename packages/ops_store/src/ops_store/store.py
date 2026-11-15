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

A store never calls `engine.begin()` or `engine.connect()`: that is a second connection beside the request's, as the
database's owner, with no caller on it (`tests/test_isolation_sites.py` lists the sites still to move).
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import ClassVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from . import isolation
from .schema import TEAM_KEY
from .team_scope import any_team


class Store:
    role: ClassVar[str | None] = None

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def tx(self) -> AbstractAsyncContextManager[AsyncConnection]:
        return isolation.isolated_tx(self.engine, role=self.role)

    def attempt(self, conn: AsyncConnection) -> AbstractAsyncContextManager[None]:
        """A savepoint around a statement that may fail and be caught, so the request's connection stays usable."""
        return isolation.attempt(conn)

    async def owner_teams(self, conn: AsyncConnection, table: sa.Table, ids: set[str], reason: str) -> dict[str, str]:
        """The owning team of each id in one query, for deciding a refusal; never for showing the rows. A row with no
        team is left out. The read is tenant-wide for `reason`, since a team's transaction cannot see another team's
        rows: inside a request that is `conn` with its scope widened for this one statement, then restored."""
        if not ids:
            return {}
        column = table.info.get(TEAM_KEY)
        if column is None:
            raise ValueError(f"{table.name} is not marked TEAM_OWNED")
        q = sa.select(table.c.id, table.c[str(column)]).where(table.c.id.in_(sorted(ids)), any_team(table, reason))
        with isolation.tenant_wide(reason):
            async with self.tx() as wide:
                return {str(i): str(team) for i, team in (await wide.execute(q)).all() if team}


__all__ = ["Store"]
