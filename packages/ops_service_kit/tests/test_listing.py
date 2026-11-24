"""The list query through a real route, by failure mode: a caller loading a whole table by asking for it, a filter
key lost or a shared key taken for a filter, and a page number the store cannot use."""

# No `from __future__ import annotations`: the test route names a local object in Depends().

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from ops_service_kit import listing
from ops_service_kit.http import install_error_handlers, page_rows
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


async def test_ids_above_the_cap_answer_400_in_the_standard_error_format() -> None:
    at_cap = "&".join(f"ids=r{i}" for i in range(listing.IDS_MAX))
    assert len((await asked(f"?{at_cap}")).json()["ids"]) == listing.IDS_MAX
    r = await asked(f"?{at_cap}&ids=one-more")
    assert (r.status_code, r.json()["error"]["code"]) == (400, "validation_failed"), r.text


def test_rows_held_in_memory_answer_the_same_page_as_a_table() -> None:
    """A list a service builds in memory searched, filtered and paged by the shared query: a search that ignores case
    or a field, a facet that counts with its own filter on, or a page past the end answering nothing, each fails."""

    rows = [
        {"id": f"t{i}", "title": f"Refund desk {i}" if i % 2 else f"Intake {i}", "kind": "agent" if i < 4 else "skill"}
        for i in range(6)
    ]

    def page(**given: Any) -> Any:
        q = listing.ListParams.model_validate({"page_size": 2, **given})
        return page_rows(
            rows, q, search=lambda r: r["title"], key=lambda r: r["id"], filters={"kind": lambda r: r["kind"]}
        )

    found = page(search="REFUND", filters={"kind": ["agent"]})
    assert [r["id"] for r in found["data"]] == ["t1", "t3"]
    assert found["pagination"]["total"] == 2
    assert found["facets"]["kind"] == {"agent": 2, "skill": 1}
    assert page(ids=["t4"], search="refund")["data"] == [rows[4]]
    last = page(page=9)
    assert (last["pagination"]["page"], [r["id"] for r in last["data"]]) == (3, ["t4", "t5"])
