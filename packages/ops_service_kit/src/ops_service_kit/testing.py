"""The statement budget every GET route is held to, for a service's tests (data-access standard, DA1 and DA6).

  # services/<x>/tests/budgets.toml
  ["GET /v1/runs"]
  queries = 4
  ["GET /v1/runs/{run_id}"]
  queries = 3
  transactions = 2          # listed: a stream's own transaction after the request's
  connections = 2           # listed: the stream's transaction checks out its own connection
  ["GET /v1/cases/{case_id}"]
  queries = 4
  hops_in_transaction = 1   # listed: a call to another service while the request's transaction is open
  ["GET /v1/access/holders"]
  queries = 6
  query = { area = "agents", team = "{team_id}" }   # sent as the query string; `{name}` takes a seeded id
  ["GET /v1/apps"]
  queries = 9
  first_queries = 24        # listed: the first call after a write rebuilds a cache; `queries` is then the next call
  ["GET /v1/auth/oidc/callback"]
  queries = 2
  status = 303              # listed: the status it answers by design, when not 200
  ["GET /v1/events"]
  not_budgeted = "a stream that never ends: no request line to read"   # not called; the reason is required

  # services/<x>/tests/conftest.py: the kit does not depend on pytest, so the service makes the fixture
  statement_budget = pytest.fixture(budget_check)

  async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
      assert await statement_budget(Path(__file__).parent / "budgets.toml") == []

The service's conftest gives three fixtures besides: `app`, its FastAPI app on the test database; `client`, an HTTP
client on that app (a test builds it; no code under `src` may); and `seed_team`, which makes a team with `n` rows in
each list and answers the headers to call as and the ids its paths need. Each GET is called
through the real middleware at 5 and at 50 rows, and the numbers are read from the request's own `http.request` line:
statements, transactions, connection checkouts, and calls to another service made while a transaction was open.
"""

from __future__ import annotations

import asyncio
import io
import json
import tomllib
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, TypedDict
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from .logging import captured_logging

# The longest a request may keep a transaction open.
MAX_OPEN_MS = 2000.0
# How far a statement budget may sit above what the route runs: a row set above its route's count would let the route
# grow unseen, so a budget more than this over the measured number fails and names it. The slack covers a statement
# one database runs and the other does not. A listed transaction, connection or service-call count has none.
QUERY_SLACK = 2
SIZES = (5, 50)


@dataclass(frozen=True)
class Seeded:
    """What `seed_team` answers: the headers a request of that team carries and the ids its path templates name."""

    headers: Mapping[str, str]
    ids: Mapping[str, str] = field(default_factory=dict[str, str])


class Answer(Protocol):
    @property
    def status_code(self) -> int: ...


class Client(Protocol):
    """The part of the test's HTTP client the budget uses (an `httpx.AsyncClient` on the app)."""

    async def get(self, url: str, *, headers: Mapping[str, str]) -> Answer: ...


# The numbers the budget reads off a request's `http.request` line; other lines carry `event` and none of them.
RequestLine = TypedDict(
    "RequestLine",
    {
        "event": str,
        "db.query_count": int,
        "db.tx_count": int,
        "db.connection_count": int,
        "http.client.calls_in_tx": int,
        "db.tx_open_ms": float,
    },
)

SeedTeam = Callable[[int], Awaitable[Seeded]]
StatementBudget = Callable[[Path], Awaitable[list[str]]]


def get_routes(app: FastAPI) -> list[str]:
    found = (r for r in iter_route_contexts(app.routes) if isinstance(r.original_route, APIRoute))
    # A route left out of the OpenAPI document is still one a caller reaches, so it is budgeted too.
    return sorted({str(r.path_format) for r in found if "GET" in (r.methods or ())})


async def over_budget(
    app: FastAPI, client: Client, seed_team: SeedTeam, budgets: Path, stream: io.StringIO
) -> list[str]:
    """One line per GET route that has no budget row, answers other than its row's `status` (200 unless listed), runs
    more statements at 50 rows than at 5, exceeds its row or sits more than QUERY_SLACK statements under it, lists
    more transactions, connections or service calls than it makes, opens more transactions or checks out more
    connections than its row lists (one of each unless it says otherwise), calls another service while a transaction
    is open (none unless listed) or keeps a transaction open too long. A row's `query` table is sent as the query
    string, each value formatted with the seeded ids. A row with `first_queries` is called twice at each size: the
    first call, right after seeding wrote, is held to `first_queries` and the second to `queries`, so a route that
    rebuilds a cache after a write is budgeted on both paths. A row with `not_budgeted = "<reason>"` is not called,
    and needs its reason."""
    rows: dict[str, dict[str, Any]] = tomllib.loads(await asyncio.to_thread(budgets.read_text))
    seen: dict[str, list[RequestLine]] = {}
    first: dict[str, list[RequestLine]] = {}
    problems: list[str] = []
    for size in SIZES:
        seeded = await seed_team(size)
        for route in get_routes(app):
            row = rows.get(f"GET {route}")
            if row is None or "not_budgeted" in row:
                continue
            query = urlencode({str(k): str(v).format(**seeded.ids) for k, v in row.get("query", {}).items()})
            url = route.format(**seeded.ids) + (f"?{query}" if query else "")
            expected = int(row.get("status", 200))
            for into in (first, seen) if "first_queries" in row else (seen,):
                stream.seek(0)
                stream.truncate()
                answer = await client.get(url, headers=dict(seeded.headers))
                lines: list[RequestLine] = [json.loads(line) for line in stream.getvalue().splitlines()]
                line = next((x for x in lines if x.get("event") == "http.request"), None)
                if answer.status_code != expected or line is None:
                    problems.append(f"GET {route}: answered {answer.status_code} at {size} rows, {expected} listed")
                    break
                into.setdefault(route, []).append(line)
    for route in get_routes(app):
        row = rows.get(f"GET {route}")
        if row is None:
            problems.append(f"GET {route}: no row in {budgets.name}")
            continue
        if "not_budgeted" in row:
            if not str(row["not_budgeted"]).strip():
                problems.append(f"GET {route}: not_budgeted needs a reason")
            continue
        measured = seen.get(route, [])
        if len(measured) != len(SIZES):
            continue
        problems += _statements(f"GET {route}", measured, int(row["queries"]))
        if "first_queries" in row:
            problems += _statements(f"GET {route} first call", first[route], int(row["first_queries"]))
            measured = [*first[route], *measured]
        opened, allowed = max(int(x["db.tx_count"]) for x in measured), int(row.get("transactions", 1))
        if opened > allowed:
            problems.append(f"GET {route}: {opened} transactions, {allowed} listed")
        checked_out, allowed = max(int(x["db.connection_count"]) for x in measured), int(row.get("connections", 1))
        if checked_out > allowed:
            problems.append(f"GET {route}: {checked_out} connection checkouts, {allowed} listed")
        hops, allowed = max(int(x["http.client.calls_in_tx"]) for x in measured), int(row.get("hops_in_transaction", 0))
        if hops > allowed:
            calls = "call" if hops == 1 else "calls"
            problems.append(f"GET {route}: {hops} service {calls} while a transaction was open, {allowed} listed")
        listed = {"transactions": opened, "connections": checked_out, "hops_in_transaction": hops}
        problems += [
            f"GET {route}: {row[key]} {key} listed, {n} measured; lower it"
            for key, n in listed.items()
            if key in row and int(row[key]) > n
        ]
        held = max(float(x["db.tx_open_ms"]) for x in measured)
        if held > MAX_OPEN_MS:
            problems.append(f"GET {route}: a transaction stayed open {held:.0f} ms, over {MAX_OPEN_MS:.0f}")
    return problems


def _statements(name: str, measured: list[RequestLine], budget: int) -> list[str]:
    """Whether one call's statements, at each size, grow with rows or sit over or too far under `budget`."""
    small, large = (int(x["db.query_count"]) for x in measured)
    out = [f"{name}: {small} statements at {SIZES[0]} rows, {large} at {SIZES[1]}"] if large > small else []
    if large > budget:
        out.append(f"{name}: {large} statements, budget {budget}")
    elif budget > large + QUERY_SLACK:
        out.append(f"{name}: budget {budget}, {large} statements measured; lower it")
    return out


def budget_check(app: FastAPI, client: Client, seed_team: SeedTeam) -> Iterator[StatementBudget]:
    """The `statement_budget` fixture, undecorated (`pytest.fixture(budget_check)`). Seeds a team at 5 and 50 rows
    per list, calls every GET through the real middleware, reads the request line, and answers one line per route
    that grows with rows, exceeds its budget in budgets.toml, opens more than one transaction or checks out more than
    one connection (unless listed), calls another service while a transaction is open (unless listed) or keeps a
    transaction open longer than 2 s. Runs on whichever database `app` is on."""
    with captured_logging("statement-budget") as stream:

        async def check(budgets: Path) -> list[str]:
            return await over_budget(app, client, seed_team, budgets, stream)

        yield check


__all__ = [
    "MAX_OPEN_MS",
    "QUERY_SLACK",
    "SeedTeam",
    "Seeded",
    "StatementBudget",
    "budget_check",
    "get_routes",
    "over_budget",
]
