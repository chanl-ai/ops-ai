"""The statement budget fixture on a small app, by failure mode: a route whose statements grow with its rows, one
over its budget, one that opens a second transaction nobody listed, and a GET with no budget row."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ops_service_kit.http import install_error_handlers
from ops_service_kit.request_timing import current
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, statement_budget

__all__ = ["statement_budget"]

BUDGETS = """
["GET /v1/flat"]
queries = 3
["GET /v1/per-row"]
queries = 80
["GET /v1/heavy/{item_id}"]
queries = 3
["GET /v1/twice"]
queries = 3
["GET /v1/stream"]
queries = 3
transactions = 2
"""


def spend(queries: int, transactions: int = 1) -> dict[str, int]:
    timing = current()  # as ops_store's engine listeners do for each statement and transaction
    assert timing is not None
    for _ in range(queries):
        timing.add_query(1.0)
    for _ in range(transactions):
        timing.add_transaction(5.0)
    return {"queries": queries}


@pytest.fixture
def seeded() -> dict[str, int]:
    return {"rows": 0}


@pytest.fixture
def app(seeded: dict[str, int]) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.get("/v1/flat")(lambda: spend(3))
    app.get("/v1/per-row")(lambda: spend(1 + seeded["rows"]))

    @app.get("/v1/heavy/{item_id}")
    async def heavy(item_id: str) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return spend(9)

    app.get("/v1/twice")(lambda: spend(2, transactions=2))
    app.get("/v1/stream")(lambda: spend(2, transactions=2))
    app.get("/v1/unlisted")(lambda: spend(1))
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://budget") as c:
        yield c


@pytest.fixture
def seed_team(seeded: dict[str, int]) -> SeedTeam:
    async def seed(n: int) -> Seeded:
        seeded["rows"] = n
        return Seeded(headers={}, ids={"item_id": "itm_1"})

    return seed


async def test_each_route_outside_its_budget_is_named_and_one_inside_it_is_not(
    statement_budget: StatementBudget, tmp_path: Path
) -> None:
    budgets = tmp_path / "budgets.toml"
    budgets.write_text(BUDGETS)
    assert await statement_budget(budgets) == [
        "GET /v1/heavy/{item_id}: 9 statements, budget 3",
        "GET /v1/per-row: 6 statements at 5 rows, 51 at 50",
        "GET /v1/twice: 2 transactions, 1 listed",
        "GET /v1/unlisted: no row in budgets.toml",
    ]
