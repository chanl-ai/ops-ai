"""Every GET route of documents-service in its statement budget (`budgets.toml`, data-access standard DA1 and DA6), by
failure mode: a list whose statements grow with its rows, a route over its row, a route that opens a second
transaction or checks out a second connection, and files-service, tools-service or the model asked while the request
holds a transaction, which the budget's service-call count cannot see, since each is faked below its service client."""

from __future__ import annotations

import io
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store import engine_for
from ops_service_kit.request_timing import current
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check

from .conftest import OPS, Make, Service
from .test_document_types import TYPE, Prices, data
from .test_document_types import Models as Reader
from .test_extractions import NOTICE, Floor
from .test_templates_install import LETTER, SOURCE, wire

BUDGETS = Path(__file__).parents[1] / "budgets.toml"
BASE = "/v1/document-types/invoice_notice"

statement_budget = pytest.fixture(budget_check)


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    """The service's own engine, whose statements and transactions the request line counts."""
    made = engine_for(database_url)
    yield made
    await made.dispose()


@pytest.fixture
def held() -> list[int]:
    """The transactions the request held open at each file read and model call."""
    return []


def _note(held: list[int]) -> None:
    timing = current()
    if timing is not None:
        held.append(timing.db_tx_open)


class HeldReader(Reader):
    def __init__(self, held: list[int]) -> None:
        super().__init__()
        self.held = held

    async def structured(self, system: str, user: str, schema: dict[str, Any], **kw: Any) -> Any:
        _note(self.held)
        return await super().structured(system, user, schema, **kw)


@pytest.fixture
def service(make: Make, held: list[int], monkeypatch: pytest.MonkeyPatch) -> Service:
    s = make(HeldReader(held), Floor(0.5), Prices())
    files = s.extractor.files
    readable, read = files.readable, files.read

    async def held_readable(*a: Any, **kw: Any) -> Any:
        _note(held)
        return await readable(*a, **kw)

    async def held_read(*a: Any, **kw: Any) -> Any:
        _note(held)
        return await read(*a, **kw)

    monkeypatch.setattr(files, "readable", held_readable)
    monkeypatch.setattr(files, "read", held_read)
    tools = wire(s, [LETTER])
    listed = tools.get

    async def held_get(path: str, **kw: Any) -> Any:
        _note(held)
        return await listed(path, **kw)

    monkeypatch.setattr(tools, "get", held_get)
    return s


@pytest.fixture
def app(service: Service) -> FastAPI:
    return service.app


class Caller:
    """The test's client as the budget calls it: a file's extraction list names the file in its query, which the
    budget's path template cannot carry."""

    def __init__(self, client: httpx.AsyncClient, file_id: list[str]) -> None:
        self.client = client
        self.file_id = file_id

    async def get(self, url: str, *, headers: Mapping[str, str]) -> httpx.Response:
        query = {"fileId": self.file_id[0]} if url == "/v1/documents/extractions" else None
        return await self.client.get(url, headers=headers, params=query)


@pytest.fixture
def notice() -> list[str]:
    return []


@pytest.fixture
async def client(service: Service, notice: list[str]) -> AsyncIterator[Caller]:
    async with service.client as http:
        yield Caller(http, notice)


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("L", (40, 20), 255).save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def seed_team(service: Service, client: Caller, notice: list[str]) -> SeedTeam:
    """`n` more of each list: document types, versions of one type, extractions of one file (each corrected, so the
    type keeps examples), and samples; plus one test run, one page image and one copy of a plugin template."""
    c = client.client
    ids: dict[str, str] = {}

    async def seed(n: int) -> Seeded:
        if not ids:
            data(await c.post("/v1/document-types", json=TYPE, headers=OPS), 201)
            notice.append(await service.stored(NOTICE))
            made = data(await c.post(f"/v1/resources/{SOURCE}:case-letter/copies", json={}, headers=OPS), 201)
            image = await service.stored(_png(), name="page.png", mime="image/png")
            ids.update(file_id=image, number="1", resource=f"{SOURCE}:case-letter", copy=made["copy"]["recordId"])
        for i in range(n):
            tag = f"{n}_{i}"
            body = {"id": f"t_{tag}", "name": f"Type {tag}", "fields": TYPE["fields"]}
            data(await c.post("/v1/document-types", json=body, headers=OPS), 201)
            data(await c.post(f"{BASE}/versions", json={"fields": TYPE["fields"], "note": tag}, headers=OPS), 201)
            read = {"fileId": notice[0], "documentTypeId": "invoice_notice"}
            eid = ids["extraction_id"] = data(await c.post("/v1/documents/extractions", json=read, headers=OPS))["id"]
            fix = {"value": f"INV-{tag}"}
            data(await c.patch(f"/v1/documents/extractions/{eid}/fields/invoice", json=fix, headers=OPS))
            sample = {"fileId": notice[0], "expected": {"invoice": "INV-2207"}}
            data(await c.post(f"{BASE}/samples", json=sample, headers=OPS), 201)
        test = data(await c.post(f"{BASE}/versions/1/test-runs", headers=OPS), 202)
        await service.types.drain()
        ids.update(type_id="invoice_notice", version="1", test_id=test["id"])
        return Seeded(headers=OPS, ids=ids)

    return seed


async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget, held: list[int]) -> None:
    problems = await statement_budget(BUDGETS)
    assert problems == [], "\n".join(problems)
    assert held, "files-service and the model were asked"
    assert set(held) == {0}, f"files-service or the model was asked with a transaction open: {held}"
