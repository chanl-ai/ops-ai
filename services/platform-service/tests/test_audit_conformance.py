"""The platform's audited write passes the shared audit suite: a change lands with its entry, and an entry the store
refuses fails the change (I7). It runs on the suite's own database, as every service's store adapter does."""

from __future__ import annotations

import asyncio
import os

import pytest
from alembic import command

from ops_platform.store.audit import TeamNameAudit
from ops_service_kit.settings import Settings
from ops_store import Backend
from ops_store.backends import backends
from ops_store.conformance import audit_suite, engine_for

from .conftest import alembic_config

BACKENDS = backends(Settings().database_url)


async def _create(backend: Backend) -> None:
    await (await engine_for(backend)).dispose()


@pytest.fixture(scope="module", params=BACKENDS, ids=[b.name for b in BACKENDS])
def backend(request: pytest.FixtureRequest) -> Backend:
    """The suite's database, created if missing and migrated on the platform chain. Synchronous because Alembic's
    environment runs its own event loop."""
    b: Backend = request.param
    asyncio.run(_create(b))
    before = os.environ.get("OPS_DATABASE_URL")
    os.environ["OPS_DATABASE_URL"] = b.url
    try:
        command.upgrade(alembic_config(), "head")
    finally:
        if before is None:
            del os.environ["OPS_DATABASE_URL"]
        else:
            os.environ["OPS_DATABASE_URL"] = before
    return b


async def test_team_rename_and_its_audit_entry_land_together(backend: Backend) -> None:
    await audit_suite(backend, lambda: TeamNameAudit.open(backend.url))
