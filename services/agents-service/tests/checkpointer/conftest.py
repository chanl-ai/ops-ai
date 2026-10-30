"""PostgreSQL for the checkpointer tests: an engine on the session's migrated test database (tests/conftest.py)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.database import open_database


@pytest.fixture
async def db(database_url: str) -> AsyncIterator[AsyncEngine]:
    e = open_database(database_url, pool_size=4)
    try:
        yield e
    finally:
        await e.dispose()
