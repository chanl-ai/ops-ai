"""The statement budget fixture on a small app, by failure mode: a route whose statements grow with its rows, one
over its budget, one that opens a second transaction or checks out a second connection nobody listed, one that calls
another service while its transaction is open, and a GET with no budget row."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from ops_service_kit.http import install_error_handlers
from ops_service_kit.request_timing import current
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check

statement_budget = pytest.fixture(budget_check)

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
["GET /v1/two-connections"]
queries = 3
["GET /v1/hop"]
queries = 3
["GET /v1/hop-listed"]
queries = 3
hops_in_transaction = 1
["GET /v1/hop-after"]
queries = 3
"""


def spend(queries: int, transactions: int = 1, *, connections: int = 1, hop: str = "") -> dict[str, int]:
    """As ops_store's pool and engine listeners and ServiceClient feed the request's timing: a checkout per
    connection, then each transaction, with a service call inside it (`hop="inside"`) or after it closed."""
    timing = current()
    assert timing is not None
    for _ in range(connections):
        timing.add_checkout(0.1, in_use=1, limit=5)
    for _ in range(queries):
        timing.add_query(1.0)
    for _ in range(transactions):
        timing.begin_transaction()
        if hop == "inside":
            timing.add_service_call()
        timing.add_transaction(5.0)
    if hop == "after":
        timing.add_service_call()
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
    app.get("/v1/two-connections")(lambda: spend(2, connections=2))
    app.get("/v1/hop")(lambda: spend(2, hop="inside"))
    app.get("/v1/hop-listed")(lambda: spend(2, hop="inside"))
    app.get("/v1/hop-after")(lambda: spend(2, hop="after"))
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
        "GET /v1/hop: 1 service call while a transaction was open, 0 listed",
        "GET /v1/per-row: 6 statements at 5 rows, 51 at 50",
        "GET /v1/twice: 2 transactions, 1 listed",
        "GET /v1/two-connections: 2 connection checkouts, 1 listed",
        "GET /v1/unlisted: no row in budgets.toml",
    ]
