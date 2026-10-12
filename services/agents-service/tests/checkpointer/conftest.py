"""PostgreSQL for the checkpointer tests: a pool on the session's migrated test database (tests/conftest.py)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from ops_checkpointer import Pool, create_pool
from ops_checkpointer.saver import asyncpg_dsn


@pytest.fixture
async def pool(database_url: str) -> AsyncIterator[Pool]:
    p = await create_pool(asyncpg_dsn(database_url), max_size=4)
    try:
        yield p
    finally:
        await p.close()
