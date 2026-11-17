"""The statement budget fixture on a small app, by failure mode: a route whose statements grow with its rows, one
over its budget, one that opens a second transaction or checks out a second connection nobody listed, one that calls
another service while its transaction is open, a GET with no budget row, one that answers other than 200 or than the
status its row lists, one left out of the budget with no reason, and a route whose row's query never reaches it."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from ops_service_kit.http import install_error_handlers
from ops_service_kit.request_timing import current
from ops_service_kit.testing import Seeded, SeedTeam, StatementBudget, budget_check

statement_budget = pytest.fixture(budget_check)

BUDGETS = """
["GET /v1/flat"]
queries = 3
["GET /v1/per-row"]
queries = 51
["GET /v1/roomy"]
queries = 5
transactions = 2
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
["GET /v1/redirect"]
queries = 3
status = 303
["GET /v1/moved"]
queries = 3
["GET /v1/asks"]
queries = 3
query = { area = "agents", item = "{item_id}" }
["GET /v1/cached"]
queries = 2
first_queries = 8
["GET /v1/cached-low"]
queries = 2
first_queries = 5
["GET /v1/callback"]
not_budgeted = "a sign-in callback: answers only with the provider's code"
["GET /v1/no-reason"]
not_budgeted = " "
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
    # `cold`: the cached routes not called since the last seed, as a bit each.
    return {"rows": 0, "cold": 0}


@pytest.fixture
def app(seeded: dict[str, int]) -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.get("/v1/flat")(lambda: spend(3))
    app.get("/v1/per-row")(lambda: spend(1 + seeded["rows"]))

    @app.get("/v1/heavy/{item_id}")
    async def heavy(item_id: str) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return spend(9)

    @app.get("/v1/asks")
    async def asks(area: str, item: str) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        # Refused without its query; over budget only when both values arrive, the path id filled in.
        return spend(9 if (area, item) == ("agents", "itm_1") else 2)

    def cached(bit: int) -> dict[str, int]:
        cold, seeded["cold"] = seeded["cold"] & bit, seeded["cold"] & ~bit
        return spend(8 if cold else 2)

    app.get("/v1/cached")(lambda: cached(1))
    app.get("/v1/cached-low")(lambda: cached(2))
    app.get("/v1/twice")(lambda: spend(2, transactions=2))
    app.get("/v1/stream")(lambda: spend(2, transactions=2))
    app.get("/v1/unlisted")(lambda: spend(1))
    # Out of the OpenAPI document, still a route a caller reaches: it needs a row like any other.
    app.get("/v1/hidden", include_in_schema=False)(lambda: spend(1))
    # Two statements and one transaction against a row of five and two: a budget left high lets the route grow unseen.
    app.get("/v1/roomy")(lambda: spend(2))
    app.get("/v1/two-connections")(lambda: spend(2, connections=2))
    app.get("/v1/hop")(lambda: spend(2, hop="inside"))
    app.get("/v1/hop-listed")(lambda: spend(2, hop="inside"))
    app.get("/v1/hop-after")(lambda: spend(2, hop="after"))

    def redirect() -> RedirectResponse:
        spend(2)
        return RedirectResponse("/v1/flat", status_code=303)

    for path in ("/v1/redirect", "/v1/moved", "/v1/callback", "/v1/no-reason"):
        app.get(path)(redirect)
    return app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://budget") as c:
        yield c


@pytest.fixture
def seed_team(seeded: dict[str, int]) -> SeedTeam:
    async def seed(n: int) -> Seeded:
        seeded["rows"], seeded["cold"] = n, 3
        return Seeded(headers={}, ids={"item_id": "itm_1"})

    return seed


async def test_each_route_outside_its_budget_is_named_and_one_inside_it_is_not(
    statement_budget: StatementBudget, tmp_path: Path
) -> None:
    budgets = tmp_path / "budgets.toml"
    budgets.write_text(BUDGETS)
    assert await statement_budget(budgets) == [
        "GET /v1/moved: answered 303 at 5 rows, 200 listed",
        "GET /v1/moved: answered 303 at 50 rows, 200 listed",
        "GET /v1/asks: 9 statements, budget 3",
        "GET /v1/cached-low first call: 8 statements, budget 5",
        "GET /v1/heavy/{item_id}: 9 statements, budget 3",
        "GET /v1/hidden: no row in budgets.toml",
        "GET /v1/hop: 1 service call while a transaction was open, 0 listed",
        "GET /v1/no-reason: not_budgeted needs a reason",
        "GET /v1/per-row: 6 statements at 5 rows, 51 at 50",
        "GET /v1/roomy: budget 5, 2 statements measured; lower it",
        "GET /v1/roomy: 2 transactions listed, 1 measured; lower it",
        "GET /v1/twice: 2 transactions, 1 listed",
        "GET /v1/two-connections: 2 connection checkouts, 1 listed",
        "GET /v1/unlisted: no row in budgets.toml",
    ]
