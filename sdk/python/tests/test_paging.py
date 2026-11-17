"""`every_page` by failure mode: a list that stops early, ends on the wrong page, breaks on no rows, or asks for a
page size the API would answer at its maximum."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from ops_ai._transport import PAGE_MAX, every_page, every_page_async


def pages(rows_per_page: list[list[str]]) -> tuple[Any, list[dict[str, Any]]]:
    asked: list[dict[str, Any]] = []

    def call(**query: Any) -> dict[str, Any]:
        asked.append(query)
        page = int(query.get("page") or 1)
        rows = rows_per_page[page - 1] if page <= len(rows_per_page) else []
        return {"data": rows, "pagination": {"page": page, "hasNext": page < len(rows_per_page)}}

    return call, asked


@pytest.mark.parametrize(
    ("rows_per_page", "query", "want_rows", "want_requests"),
    [
        ([["a"], ["b"], ["c"]], {}, ["a", "b", "c"], 3),
        ([["a", "b"], ["c"]], {}, ["a", "b", "c"], 2),
        ([[]], {}, [], 1),
        ([["a"], ["b"]], {"page_size": 200}, ["a", "b"], 2),
        ([["a"], ["b"]], {"page_size": 10, "search": "x"}, ["a", "b"], 2),
    ],
)
def test_every_page_follows_has_next_and_never_asks_above_the_maximum(
    rows_per_page: list[list[str]], query: dict[str, Any], want_rows: list[str], want_requests: int
) -> None:
    call, asked = pages(rows_per_page)
    assert every_page(call, **query) == want_rows
    assert len(asked) == want_requests
    assert all(q["page_size"] <= PAGE_MAX for q in asked)
    assert asked[0]["page_size"] == min(query.get("page_size", PAGE_MAX), PAGE_MAX)
    assert all(q.get("search") == query.get("search") for q in asked[1:] or asked)


def test_every_page_async_follows_every_page() -> None:
    call, _ = pages([["a"], ["b"], ["c"]])

    async def acall(**query: Any) -> Any:
        return call(**query)

    assert asyncio.run(every_page_async(acall)) == ["a", "b", "c"]
