"""uc-560 every request shows where its time went, api layer: docs/usecases/console/screen-speed.md. platform-service
and agents-service with platform sign-in and OPS_REQUEST_TIMING on: a database route's JSON line and Server-Timing,
a malformed X-Request-Id replaced, one id across agents → platform and in the error envelope, and two overlapping
requests each counting only their own queries. Then a platform-service with timing off writes no line. No model call."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from pathlib import Path
from typing import Any

os.environ["OPS_REQUEST_TIMING"] = "1"

import httpx
from fastapi import FastAPI
from sqlalchemy import text
from usecase_harness import (
    AGENTS_PORT,
    LOG_DIR,
    PLATFORM_INTERNAL_PORT,
    PLATFORM_PORT,
    agents,
    bearer,
    check,
    finish,
    pg_url,
    platform,
    signed_in,
)

from ops_service_kit.http import install_error_handlers, ok
from ops_store.database import open_database

JAMES = "j.richardson@harborpine.example"
AUTH = {
    "OPS_AUTH_MODE": "platform",
    "OPS_PLATFORM_URL": f"http://127.0.0.1:{PLATFORM_PORT}",
    "OPS_PLATFORM_INTERNAL_PORT": str(PLATFORM_INTERNAL_PORT),
}
AGENTS_LOG = LOG_DIR / f"agents-{AGENTS_PORT}.log"
PLATFORM_LOG = LOG_DIR / f"platform-{PLATFORM_PORT}.log"


def rid() -> str:
    return f"uc560-{secrets.token_hex(6)}"


def mark(log: Path) -> int:
    return log.stat().st_size if log.exists() else 0


def lines_since(log: Path, at: int) -> list[str]:
    with log.open("rb") as fh:
        fh.seek(at)
        return fh.read().decode("utf-8", "replace").splitlines()


def request_lines(log: Path, at: int, request_id: str) -> list[dict[str, Any]]:
    """The ops.request lines for `request_id`: each must parse whole, as one JSON object on its own line."""
    found: list[dict[str, Any]] = []
    for line in lines_since(log, at):
        if request_id in line and line.startswith("{"):
            found.append(json.loads(line))
    return found


def server_timing(r: httpx.Response) -> dict[str, float]:
    entries: dict[str, float] = {}
    for part in r.headers.get("server-timing", "").split(","):
        name, _, dur = part.strip().partition(";dur=")
        if name and dur:
            entries[name] = float(dur)
    return entries


CLASSIFY = {
    "schemaVersion": 2,
    "id": f"uc560_triage_{secrets.token_hex(2)}",
    "name": "Triage by meaning",
    "nodes": [
        {"id": "start", "type": "ops.trigger.request", "typeVersion": 1, "parameters": {}},
        {
            "id": "sort",
            "type": "ops.ai.classify",
            "typeVersion": 1,
            "parameters": {
                "text": "$.input.body",
                "categories": [
                    {"name": "fraud", "description": "The customer reports a payment they did not make"},
                    {"name": "billing", "description": "A question about fees or a statement"},
                ],
                "minConfidence": 0.6,
            },
        },
        *(
            {"id": f"end_{o}", "type": "ops.flow.end", "typeVersion": 1, "parameters": {"outcome": o}}
            for o in ("billing", "failed", "fraud", "person")
        ),
    ],
    "connections": [
        {"from": {"node": f}, "to": {"node": to, "port": "in"}} | {"from": {"node": f, "port": port}}
        for f, port, to in [
            ("start", "payload", "sort"),
            ("sort", "fraud", "end_fraud"),
            ("sort", "billing", "end_billing"),
            ("sort", "otherwise", "end_person"),
            ("sort", "error", "end_failed"),
        ]
    ],
}


async def overlapping() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """An app built here on the real middleware and engine listeners, against the use case database: one request
    sleeps in SQL while three others answer with three quick queries each, all at once."""
    db = open_database(pg_url())
    app = FastAPI(title="uc560-overlap")
    install_error_handlers(app)

    @app.get("/slow")
    async def slow() -> Any:  # pyright: ignore[reportUnusedFunction]
        async with db.connect() as c:
            await c.execute(text("SELECT pg_sleep(0.6)"))
        return ok({})

    @app.get("/fast")
    async def fast() -> Any:  # pyright: ignore[reportUnusedFunction]
        async with db.connect() as c:
            for _ in range(3):
                await c.execute(text("SELECT 1"))
        return ok({})

    seen: list[dict[str, Any]] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            seen.append(json.loads(record.getMessage()))

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://overlap") as c:
            await c.get("/fast")  # builds the middleware, and with it the ops.request logger
            logging.getLogger("ops.request").addHandler(Keep())
            seen.clear()

            async def fast_after_start() -> httpx.Response:
                await asyncio.sleep(0.1)
                return await c.get("/fast")

            await asyncio.gather(c.get("/slow"), *(fast_after_start() for _ in range(3)))
    finally:
        await db.dispose()
    slow_line = next((s for s in seen if s["http.route"] == "/slow"), {})
    return slow_line, [s for s in seen if s["http.route"] == "/fast"]


with platform() as (api, _), agents(env=AUTH) as ag:
    J = bearer(signed_in(api, JAMES), "team_ops")

    # Step 1: a database route, with James's own id.
    mine = rid()
    at = mark(AGENTS_LOG)
    r = ag.get("/v1/workflows/definitions", headers=J | {"X-Request-Id": mine})
    timing = server_timing(r)
    check(
        "1 the response returns his id and Server-Timing with app and db",
        r.status_code == 200 and r.headers.get("x-request-id") == mine and {"app", "db"} <= timing.keys(),
        {"status": r.status_code, "id": r.headers.get("x-request-id"), "server-timing": r.headers.get("server-timing")},
    )
    logged = request_lines(AGENTS_LOG, at, mine)
    line = logged[0] if logged else {}
    check(
        "1 agents-service logs one JSON line with the route template, status, queries, team and id",
        len(logged) == 1
        and line.get("http.route") == "/v1/workflows/definitions"
        and line.get("http.response.status_code") == 200
        and line.get("db.query_count", 0) >= 1
        and line.get("db.duration_ms", -1) >= 0
        and line.get("team") == "team_ops",
        logged,
    )

    # Step 2: ids that must not reach the logs.
    long_id, spaced = "a" * 10_000, "has a space"
    at = mark(AGENTS_LOG)
    long_r = ag.get("/v1/workflows/definitions", headers=J | {"X-Request-Id": long_id})
    spaced_r = ag.get("/v1/workflows/definitions", headers=J | {"X-Request-Id": spaced})
    after = "\n".join(lines_since(AGENTS_LOG, at))
    check(
        "2 a 10 kB id and one with a space are each replaced by a minted req_ id, and neither is logged",
        long_r.headers.get("x-request-id", "").startswith("req_")
        and spaced_r.headers.get("x-request-id", "").startswith("req_")
        and long_id not in after
        and spaced not in after,
        {"long": long_r.headers.get("x-request-id"), "spaced": spaced_r.headers.get("x-request-id")},
    )

    # Step 3: one id across agents → platform, and in the error envelope.
    across = rid()
    at_agents, at_platform = mark(AGENTS_LOG), mark(PLATFORM_LOG)
    refused = ag.post("/v1/workflows/definitions", json={"definition": CLASSIFY}, headers=J | {"X-Request-Id": across})
    envelope = refused.json().get("error", {})
    check(
        "3 the refused save's envelope names his id",
        refused.status_code == 422 and envelope.get("requestId") == across,
        {"status": refused.status_code, "error": envelope},
    )
    on_agents = request_lines(AGENTS_LOG, at_agents, across)
    on_platform = request_lines(PLATFORM_LOG, at_platform, across)
    check(
        "3 agents-service and platform-service's policy read each log a line with that id",
        len(on_agents) == 1
        and on_agents[0].get("http.response.status_code") == 422
        and any(str(p.get("http.route", "")).startswith("/v1/policies/") for p in on_platform),
        {"agents": on_agents, "platform": on_platform},
    )

    # Step 4: overlapping requests keep their own database time and query count.
    slow_line, fast_lines = asyncio.run(overlapping())
    check(
        "4 the slow request counts its one sleeping query, and each fast one only its own three",
        slow_line.get("db.query_count") == 1
        and slow_line.get("db.duration_ms", 0) >= 500
        and len(fast_lines) == 3
        and all(f.get("db.query_count") == 3 and f.get("db.duration_ms", 1e9) < 500 for f in fast_lines),
        {"slow": slow_line, "fast": fast_lines},
    )

# Step 5: timing off.
with platform(env={"OPS_REQUEST_TIMING": ""}) as (api, _):
    quiet = rid()
    at = mark(PLATFORM_LOG)
    r = api.post(
        "/v1/auth/sign-in", json={"email": JAMES, "password": "northfield-demo"}, headers={"X-Request-Id": quiet}
    )
    check(
        "5 with timing off the id is returned, with no Server-Timing and no JSON line",
        r.status_code == 200
        and r.headers.get("x-request-id") == quiet
        and "server-timing" not in r.headers
        and not request_lines(PLATFORM_LOG, at, quiet),
        {"status": r.status_code, "headers": dict(r.headers)},
    )

finish()
