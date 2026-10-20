"""The schema a service needs, checked before it serves: its own migration chain's head against the revisions the
database records. A service starts only when its head is recorded. An older revision of its chain is refused as
behind, naming both, so an upgrade that was not applied fails at start rather than as a missing column halfway through
a request. A database that records none of this build's revisions (not installed, or a newer release's schema under an
older image) is refused too: migrations do not roll back, so a rollback restores the database with the image.

The version tables are found by name prefix (`alembic_version*`) through SQLAlchemy's inspector and the chain's
revision by content, so every supported dialect answers it; a table the role may not read (another service's) is
skipped.

    require_current_schema(settings.database_url, Path(ops_files.__file__).parents[2] / "migrations")
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import sqlalchemy as sa
from alembic.script import ScriptDirectory
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class SchemaBehindError(RuntimeError):
    """The database's recorded revision is missing or older than this build's chain."""


async def recorded_revisions(engine: AsyncEngine) -> list[str]:
    async with engine.connect() as c:
        names = await c.run_sync(lambda sync: sa.inspect(sync).get_table_names())
    tables = [n for n in names if n.startswith("alembic_version")]
    found: list[str] = []
    for table in tables:
        # information_schema lists the tables a role holds any right on; a runtime role reads only its own.
        try:
            async with engine.connect() as c:
                found += [str(r[0]) for r in await c.execute(sa.text(f'SELECT version_num FROM "{table}"'))]
        except DBAPIError:
            continue
    return found


def verdict(chain: ScriptDirectory, recorded: list[str], name: str) -> str | None:
    """None when the database records this chain's head; else why the service must not start."""
    heads = set(chain.get_heads())
    revisions = {r.revision for r in chain.walk_revisions()}
    mine = [r for r in recorded if r in revisions]
    if any(r in heads for r in mine):
        return None
    need = ", ".join(sorted(heads))
    if mine:
        return (
            f"{name}: the database's schema is behind: it records {', '.join(mine)}, this build needs {need}. "
            "Apply the upgrade first."
        )
    return (
        f"{name}: the database records none of this build's revisions (it needs {need}): the schema is not installed, "
        "or it belongs to another release."
    )


async def check_schema(engine: AsyncEngine, migrations: Path) -> str | None:
    return verdict(ScriptDirectory(str(migrations)), await recorded_revisions(engine), migrations.parent.name)


def require_current_schema(database_url: str, migrations: Path) -> None:
    """Raises SchemaBehindError before a service serves on a schema older than its chain."""

    async def go() -> str | None:
        engine = create_async_engine(database_url)
        try:
            return await check_schema(engine, migrations)
        finally:
            await engine.dispose()

    problem = asyncio.run(go())
    if problem:
        raise SchemaBehindError(problem)
