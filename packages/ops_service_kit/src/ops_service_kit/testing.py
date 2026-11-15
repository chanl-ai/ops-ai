"""The statement budget every GET route is held to, for a service's tests (data-access standard, DA1 and DA6).

  # services/<x>/tests/budgets.toml
  ["GET /v1/runs"]
  queries = 4
  ["GET /v1/runs/{run_id}"]
  queries = 3
  transactions = 2          # listed: a stream's own transaction after the request's

  async def test_every_get_stays_in_its_budget(statement_budget: StatementBudget) -> None:
      assert await statement_budget(Path(__file__).parent / "budgets.toml") == []

The service's conftest gives three fixtures: `app`, its FastAPI app on the test database; `client`, an HTTP client on
that app (a test builds it; no code under `src` may); and `seed_team`, which makes a team with `n` rows in each list
and answers the headers to call as and the ids its paths need. Each GET is called
through the real middleware at 5 and at 50 rows, and the numbers are read from the request's own `http.request` line.
A hop to another service while the transaction is open is not seen here yet: nothing on the line records one.
"""

from __future__ import annotations

import io
import json
import tomllib
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from .logging import captured_logging

# The longest a request may keep a transaction open.
MAX_OPEN_MS = 2000.0
SIZES = (5, 50)


@dataclass(frozen=True)
class Seeded:
    """What `seed_team` answers: the headers a request of that team carries and the ids its path templates name."""

    headers: Mapping[str, str]
    ids: Mapping[str, str] = field(default_factory=dict[str, str])


SeedTeam = Callable[[int], Awaitable[Seeded]]
StatementBudget = Callable[[Path], Awaitable[list[str]]]


def get_routes(app: FastAPI) -> list[str]:
    found = (r for r in iter_route_contexts(app.routes) if isinstance(r.original_route, APIRoute))
    return sorted({str(r.path_format) for r in found if "GET" in (r.methods or ()) and r.include_in_schema})


async def over_budget(
    app: FastAPI, client: httpx.AsyncClient, seed_team: SeedTeam, budgets: Path, stream: io.StringIO
) -> list[str]:
    """One line per GET route that has no budget row, runs more statements at 50 rows than at 5, exceeds its row,
    opens more transactions than its row lists (one unless it says otherwise) or keeps one open too long."""
    rows: dict[str, dict[str, Any]] = tomllib.loads(budgets.read_text())
    seen: dict[str, list[dict[str, Any]]] = {}
    problems: list[str] = []
    for size in SIZES:
        seeded = await seed_team(size)
        for route in get_routes(app):
            if f"GET {route}" not in rows:
                continue
            stream.seek(0)
            stream.truncate()
            answer = await client.get(route.format(**seeded.ids), headers=dict(seeded.headers))
            lines = [json.loads(line) for line in stream.getvalue().splitlines()]
            line = next((x for x in lines if x.get("event") == "http.request"), None)
            if answer.status_code != 200 or line is None:
                problems.append(f"GET {route}: answered {answer.status_code} at {size} rows")
                continue
            seen.setdefault(route, []).append(line)
    for route in get_routes(app):
        row = rows.get(f"GET {route}")
        if row is None:
            problems.append(f"GET {route}: no row in {budgets.name}")
            continue
        measured = seen.get(route, [])
        if len(measured) != len(SIZES):
            continue
        small, large = (int(x["db.query_count"]) for x in measured)
        if large > small:
            problems.append(f"GET {route}: {small} statements at {SIZES[0]} rows, {large} at {SIZES[1]}")
        if large > int(row["queries"]):
            problems.append(f"GET {route}: {large} statements, budget {row['queries']}")
        opened, allowed = max(int(x["db.tx_count"]) for x in measured), int(row.get("transactions", 1))
        if opened > allowed:
            problems.append(f"GET {route}: {opened} transactions, {allowed} listed")
        held = max(float(x["db.tx_open_ms"]) for x in measured)
        if held > MAX_OPEN_MS:
            problems.append(f"GET {route}: a transaction stayed open {held:.0f} ms, over {MAX_OPEN_MS:.0f}")
    return problems


@pytest.fixture
def statement_budget(app: FastAPI, client: httpx.AsyncClient, seed_team: SeedTeam) -> Any:
    """Seeds a team at 5 and 50 rows per list, calls every GET through the real middleware, reads db.query_count,
    db.tx_count and db.tx_open_ms from the request line, and answers one line per route that grows with rows,
    exceeds its budget in budgets.toml, opens more than one transaction (unless listed) or keeps it open longer than
    2 s. Runs on whichever database `app` is on."""
    with captured_logging("statement-budget") as stream:

        async def check(budgets: Path) -> list[str]:
            return await over_budget(app, client, seed_team, budgets, stream)

        yield check


__all__ = ["MAX_OPEN_MS", "SeedTeam", "Seeded", "StatementBudget", "get_routes", "over_budget", "statement_budget"]
