"""documents-service's tests: its own chain on the test database (make test sets OPS_TEST_DATABASE_URL), files-service
faked at its documented routes (ops_files_client.testing), and people signed in with a real role in their team."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
import pytest
from fastapi import FastAPI, Header, Request
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_documents.app import create_documents_app
from ops_documents.document_types import DocumentTypes, Prices
from ops_documents.extraction import Extractor, Floors, Models
from ops_documents.files import Files
from ops_documents.layouts import Layouts
from ops_documents.store import DocumentTypesStore, ExtractionsStore, LayoutsStore
from ops_files_client.testing import FakeFilesService
from ops_identity import Auth, Principal
from ops_identity.fastapi import current_caller, current_principal
from ops_service_kit.contract import response_checker
from ops_service_kit.settings import Settings
from ops_service_kit.testdb import isolate_from_stack
from ops_store import isolation

OPS = {"X-Team-Id": "team_ops"}


def pytest_configure(config: pytest.Config) -> None:
    isolate_from_stack()


@pytest.fixture(scope="session")
def database_url() -> str:
    from alembic import command  # noqa: PLC0415
    from alembic.config import Config  # noqa: PLC0415

    from ops_service_kit.testdb import refusal  # noqa: PLC0415

    url = Settings().database_url
    if (why := refusal(url, os.environ.get("OPS_TEST_DATABASE_URL"))) is not None:
        pytest.fail(why)
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    return url


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
            email="j.richardson@northfieldbank.com",
            name="j.richardson",
            tenant_id=tenant,
            team_id=team,
            team_ids=[team],
            roles={team: role},
            scopes=[],
            auth_method="session",
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


@pytest.fixture
def make(engine: AsyncEngine, tenant: str) -> Make:
    def build(
        models: Models | None = None, floors: Floors | None = None, prices: Prices | None = None, role: str = "builder"
    ) -> Service:
        fake = FakeFilesService()
        files = Files(fake.client(service="documents", scopes=["files:view", "files:edit"]))
        layouts = Layouts(files, LayoutsStore(engine))
        extractor = Extractor(files, ExtractionsStore(engine), models, floors, layouts=layouts)
        types = DocumentTypes(DocumentTypesStore(engine), files, extractor, prices)
        extractor.types = types
        auth = Auth.for_dev(Settings(), audience="documents", name="james", email="j@x", tenant_id=tenant)
        app = create_documents_app(engine=engine, extractor=extractor, document_types=types, auth=auth, layouts=layouts)
        sign_in(app, tenant, role)
        hooks: dict[str, Any] = {"response": [response_checker(app)]}
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://documents", event_hooks=hooks
        )
        return Service(client, app, extractor, types, fake, tenant)

    return build
