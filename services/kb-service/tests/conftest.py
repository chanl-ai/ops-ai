"""kb-service in-process on the compose PostgreSQL (`make db-up`), migrated by its own chain."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4
from weakref import WeakKeyDictionary

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_identity import Auth, CurrentPrincipal
from ops_kb.agents import AgentDirectory, StaticAgents
from ops_kb.app import create_kb_app, who
from ops_kb.files import FileIntake, KnowledgeFiles
from ops_kb.service import Who
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack, refusal

ROOT = Path(__file__).parents[1]


def pytest_configure(config: pytest.Config) -> None:
    isolate_from_stack()
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)


@pytest.fixture(scope="session")
def database_url() -> str:
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    return Settings().database_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


# Each client's file store, so a test can put bytes in it the way the console uploads to Files before adding the id.
intakes: WeakKeyDictionary[httpx.AsyncClient, FileIntake] = WeakKeyDictionary()


def kb_client(
    engine: AsyncEngine,
    tenant: str,
    email: str = "james@northfieldbank.com",
    files: FileIntake | None = None,
    *,
    admin: bool = False,
    agents: AgentDirectory | None = None,
) -> httpx.AsyncClient:
    """kb-service as the dev user `email` in `tenant`; each test runs on its own tenant's rows and its own files."""
    auth = Auth.for_dev(Settings(), audience="kb", name=email.split("@", maxsplit=1)[0], email=email, tenant_id=tenant)
    intake = files or KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    app = create_kb_app(
        engine,
        auth=auth,
        files=intake,
        agents=agents or StaticAgents(),
    )
    if admin:
        # Dev sign-in carries no roles, and `can()` passes the dev caller as it would a team admin (c-149).
        async def as_admin(p: CurrentPrincipal) -> Who:
            return Who(tenant_id=p.tenant_id, email=p.email, team_id=p.team_id, caller=p)

        app.dependency_overrides[who] = as_admin
    # Every JSON response is checked against the app's own OpenAPI document.
    hooks = {"response": [response_checker(app)]}
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kb", event_hooks=hooks)
    intakes[client] = intake
    return client


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid4().hex[:10]}"


@pytest.fixture
async def client(engine: AsyncEngine, tenant: str, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    async with kb_client(engine, tenant, files=KnowledgeFiles(tmp_path)) as c:
        yield c
