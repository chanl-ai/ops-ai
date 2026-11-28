"""documents-service's tests: its own chain on the test database (make test sets OPS_TEST_DATABASE_URL), files-service
faked at its documented routes (ops_files_client.testing), and people signed in with a real role in their team."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable, Coroutine, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Header, Request
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_documents.app import create_documents_app
from ops_documents.document_types import DocumentTypes, Prices
from ops_documents.extraction import Extractor, Floors, Models
from ops_documents.files import Files
from ops_documents.readings import Readings
from ops_documents.renditions import Renditions
from ops_documents.store import DocumentTypesStore, ExtractionsStore, ReadingsStore
from ops_files_client.testing import FakeFilesService
from ops_identity import Auth, Principal
from ops_identity.fastapi import current_caller, current_principal
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testapps import released_apps
from ops_service_kit.testdb import isolate_from_stack, use_worker_database
from ops_store import background, isolation
from ops_store.testing import DATABASES, NO_SQL_SERVER, postgresql_only, sql_server_schema

OPS = {"X-Team-Id": "team_ops"}


def pytest_configure(config: pytest.Config) -> None:
    use_worker_database()
    isolate_from_stack()
    config.addinivalue_line("markers", "postgresql_only(why): runs on PostgreSQL only, for the reason given")
    config.addinivalue_line("markers", "lifespan_supervisor: the test's own app lifespan must hold the supervisor")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    keep, dropped = postgresql_only(items)
    if dropped:
        config.hook.pytest_deselected(items=[i for i in items if i not in keep])
        items[:] = keep
        terminal = config.pluginmanager.get_plugin("terminalreporter")
        for nodeid, why in dropped:
            if terminal is not None:
                terminal.write_line(f"postgresql only: {nodeid}: {why}")


@pytest.fixture(scope="session", params=DATABASES)
def database_url(request: pytest.FixtureRequest) -> Iterator[str]:
    if request.param == "postgresql":
        from alembic import command  # noqa: PLC0415
        from alembic.config import Config  # noqa: PLC0415

        from ops_service_kit.testdb import refusal  # noqa: PLC0415

        url = Settings().database_url
        if (why := refusal(url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
            pytest.fail(why)
        command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
        yield url
        return
    with sql_server_schema(
        "documents", os.environ.get("OPS_MSSQL_SERVER"), os.environ.get("MSSQL_SA_PASSWORD")
    ) as mssql_url:
        if mssql_url is None:
            pytest.skip(NO_SQL_SERVER)
        yield mssql_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    await engine.dispose()


@pytest.fixture
def tenant() -> str:
    return f"t_{uuid.uuid4().hex[:10]}"


def sign_in(app: FastAPI, tenant: str, role: str) -> None:
    """A person with a real role in the team they act in (X-Team-Id, else team_ops), so `can()` decides as in a
    deployment; a bearer token (a service) is resolved as usual."""

    async def as_person(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_caller(request, authorization=authorization)
        team = x_team_id or "team_ops"
        p = Principal(
            kind="person",
            sub="usr_dev",
            email="j.richardson@harborpine.example",
            name="j.richardson",
            tenant_id=tenant,
            team_id=team,
            team_ids=[team],
            roles={team: role},
            scopes=[],
            auth_method="session",
            # The workspace's Security team, which platform-service names in every person's token.
            security_team="team_security",
        )
        # The stand-in replaces ops_identity's dependency, so it enters the request's context as that one does.
        isolation.enter_caller(p, dev=False)
        return p

    async def as_person_only(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        x_team_id: Annotated[str | None, Header()] = None,
    ) -> Principal:
        if authorization:
            return await current_principal(request, authorization=authorization)
        return await as_person(request, None, x_team_id)

    app.dependency_overrides[current_caller] = as_person
    app.dependency_overrides[current_principal] = as_person_only


@dataclass
class Service:
    """One documents-service process over a faked files-service."""

    client: httpx.AsyncClient
    app: FastAPI
    extractor: Extractor
    types: DocumentTypes
    files: FakeFilesService
    tenant: str

    async def stored(
        self,
        body: bytes,
        *,
        name: str = "notice.txt",
        team: str = "team_ops",
        clean: bool = True,
        mime: str = "text/plain",
    ) -> str:
        """A file in the faked files-service, in `team`, scanned clean unless `clean=False`."""
        f = await self.files.client().write(
            self.tenant, team, body, name=name, mime=mime, purpose="case_attachment", uploaded_by="x"
        )
        if clean:
            await self.files.client(service="scanner", scopes=["files:decide"]).report_scan(
                self.tenant, f.file.id, status="clean", engine="clamav"
            )
        return f.file.id


Make = Callable[..., Service]


async def tenant_outbox(engine: AsyncEngine, tenant: str, q: sa.Executable) -> list[dict[str, Any]]:
    """The tenant's outbox rows, read in the tenant's scope: SQL Server applies its row policies to every user, so a
    read outside the tenant's session context finds none."""
    with isolation.tenant_wide("test: the tenant's outbox rows", tenant_id=tenant):
        async with isolation.isolated_tx(engine) as conn:
            return [dict(r) for r in (await conn.execute(q)).mappings()]


@pytest.fixture
def make(engine: AsyncEngine, tenant: str) -> Make:
    def build(
        models: Models | None = None,
        floors: Floors | None = None,
        prices: Prices | None = None,
        role: str = "builder",
        type_uses: Any = None,
        *,
        background: Sequence[Callable[[], Coroutine[Any, Any, None]]] = (),
        pictures: Any = None,
        converter: Any = None,
        rendition_scan: str = "clean",
    ) -> Service:
        fake = FakeFilesService()
        files = Files(fake.client(service="documents", scopes=["files:view", "files:edit"]))
        readings = Readings(files, ReadingsStore(engine), pictures=pictures)
        if converter is not None:
            writer = fake.client(service="documents", scopes=["files:view", "files:create", "files:edit"])
            readings.renditions = Renditions(converter, writer, scan_wait_s=0.2, scan_poll_s=0.02)
            # A drawn PDF clears its scan at once unless the test holds it (rendition_scan="pending").
            fake.clean_on_write = () if rendition_scan == "pending" else ("knowledge_rendition",)
        extractor = Extractor(files, ExtractionsStore(engine), models, floors, readings=readings)
        types = DocumentTypes(DocumentTypesStore(engine), files, extractor, prices)
        extractor.types = types
        auth = Auth.for_dev(Settings(), audience="documents", name="james", email="j@x", tenant_id=tenant)
        app = create_documents_app(
            engine=engine,
            extractor=extractor,
            document_types=types,
            auth=auth,
            readings=readings,
            type_uses=type_uses,
            background=background,
        )
        sign_in(app, tenant, role)
        hooks: dict[str, Any] = {"response": [response_checker(app)]}
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://documents", event_hooks=hooks
        )
        return Service(client, app, extractor, types, fake, tenant)

    return build


@pytest.fixture(autouse=True)
def _release_apps() -> Iterator[None]:
    yield from released_apps()


@pytest.fixture(autouse=True)
async def _supervisor(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """The supervisor a lifespan holds, around each test: requests queue readings, extractions and type tests onto it
    without the lifespan running. Leaving it cancels whatever a test left running. A test marked
    `lifespan_supervisor` gets none, so it fails unless the app's own lifespan holds one."""
    if "lifespan_supervisor" in request.keywords:
        yield
        return
    async with background.supervisor():
        yield
