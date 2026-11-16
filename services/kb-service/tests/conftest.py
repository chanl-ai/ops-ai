"""kb-service in-process on the compose PostgreSQL (`make db-up`), migrated by its own chain, and on a scratch SQL
Server database holding the chain's golden DDL when OPS_MSSQL_SERVER and MSSQL_SA_PASSWORD are set
(ops_store.testing). The store, isolation and outbox tests in BOTH_DATABASES run on both; the rest read the
PostgreSQL-only search lanes or have not been run on SQL Server yet, and run on PostgreSQL alone."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
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
from ops_kb.ai import AiClients
from ops_kb.app import create_kb_app, who
from ops_kb.embedding import Embedder
from ops_kb.files import FileIntake, KnowledgeFiles
from ops_kb.query_steps import QueryModel
from ops_kb.readings import Readings
from ops_kb.service import Who
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack, refusal, unanswered_endpoints
from ops_store.testing import DATABASES, NO_SQL_SERVER, postgresql_only, sql_server_schema

from .readings_fake import LocalReadings

ROOT = Path(__file__).parents[1]
# The test files that run on SQL Server too; the store-mssql job in .github/workflows/ci.yml runs the same list.
BOTH_DATABASES = frozenset(
    {
        "test_kb_isolation.py",
        "test_kb_changed.py",
        "test_team_isolation.py",
        "test_background_tenants.py",
        "test_system_user_predicates.py",
        "test_lookup_indexes.py",
    }
)


def pytest_configure(config: pytest.Config) -> None:
    isolate_from_stack()
    # The app asks agents-service who uses a knowledge base and sends it events; a test that needs an answer passes
    # its own `agents` or `events_to`, and the rest get an address nothing answers on.
    unanswered_endpoints("agents")
    # Before any fixture or migration: the test database only, never the live one (ops_service_kit.testdb).
    if (why := refusal(Settings().database_url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.exit(why, returncode=4)
    config.addinivalue_line("markers", "postgresql_only(why): runs on PostgreSQL only, for the reason given")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if item.path.name not in BOTH_DATABASES and item.get_closest_marker("postgresql_only") is None:
            item.add_marker(pytest.mark.postgresql_only("not in BOTH_DATABASES"))
    keep, dropped = postgresql_only(items)
    if dropped:
        config.hook.pytest_deselected(items=[i for i in items if i not in keep])
        items[:] = keep
        terminal = config.pluginmanager.get_plugin("terminalreporter")
        for nodeid, why in dropped:
            if terminal is not None and why != "not in BOTH_DATABASES":
                terminal.write_line(f"postgresql only: {nodeid}: {why}")


@pytest.fixture(scope="session", params=DATABASES)
def database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
        yield Settings().database_url
        return
    with sql_server_schema("kb", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")) as url:
        if url is None:
            pytest.skip(NO_SQL_SERVER)
        yield url


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
    email: str = "james@harborpine.example",
    files: FileIntake | None = None,
    *,
    admin: bool = False,
    agents: AgentDirectory | None = None,
    readings: Readings | None = None,
    embedder: Embedder | None = None,
    ai_clients: AiClients | None = None,
    query_model: QueryModel | None = None,
) -> httpx.AsyncClient:
    """kb-service as the dev user `email` in `tenant`; each test runs on its own tenant's rows and its own files."""
    auth = Auth.for_dev(Settings(), audience="kb", name=email.split("@", maxsplit=1)[0], email=email, tenant_id=tenant)
    intake = files or KnowledgeFiles(Path(mkdtemp(prefix="kb-files-")))
    app = create_kb_app(
        engine,
        auth=auth,
        files=intake,
        agents=agents or StaticAgents(),
        readings=readings or LocalReadings(intake),
        embedder=embedder,
        ai_clients=ai_clients,
        query_model=query_model,
    )
    if admin:
        # Dev sign-in carries no roles, and `can()` passes the dev caller as it would a team admin.
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
