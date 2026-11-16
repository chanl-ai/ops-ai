"""The list query through a real route, by failure mode: a caller loading a whole table by asking for it, a filter
key lost or a shared key taken for a filter, and a page number the store cannot use."""

# No `from __future__ import annotations`: the test route names a local object in Depends().

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ops_service_kit import listing
from ops_service_kit.http import install_error_handlers
from ops_service_kit.listing import ListQuery
from ops_service_kit.settings import Settings


async def asked(query: str) -> httpx.Response:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/v1/runs")
    async def runs(q: ListQuery) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return q.model_dump()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kit") as c:
        return await c.get(f"/v1/runs{query}")


async def test_a_list_query_is_capped_at_the_maximum_and_every_other_key_is_a_filter() -> None:
    s = Settings()
    plain = (await asked("")).json()
    assert (plain["page"], plain["page_size"], plain["filters"], plain["ids"]) == (1, s.page_size_default, {}, None)
    r = await asked(
        "?page=2&pageSize=100000&search=refund&sortBy=startedAt&sortOrder=asc&ids=a&ids=b&status=open&status=held&agent=a1&empty="
    )
    assert r.json() == {
        "page": 2,
        "page_size": s.page_size_max,
        "search": "refund",
        "sort_by": "startedAt",
        "sort_order": "asc",
        "ids": ["a", "b"],
        "filters": {"status": ["open", "held"], "agent": ["a1"]},
    }


async def test_a_list_request_reads_no_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    listing.page_sizes.cache_clear()  # as in a new process: the app's start must read them
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/v1/runs")
    async def runs(q: ListQuery) -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        return q.model_dump()

    read: list[None] = []

    def counted() -> Settings:
        read.append(None)
        return Settings()

    monkeypatch.setattr(listing, "Settings", counted)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://kit") as c:
        for query in ("", "?pageSize=100000"):
            assert (await c.get(f"/v1/runs{query}")).status_code == 200
    assert read == []


async def test_a_page_or_order_the_store_cannot_use_is_refused() -> None:
    for query in ("?page=0", "?pageSize=0", "?sortOrder=up"):
        r = await asked(query)
        assert (r.status_code, r.json()["error"]["code"]) == (400, "validation_failed"), query
