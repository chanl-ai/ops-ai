"""Mailbox adapter cost on PostgreSQL: SQL statements and checkpointer calls per message, first poll and replay.

Runs the 100-message fixture through the real adapter and the real asyncpg checkpointer on a fresh scratch database
(`ops_mailbox_cost`, dropped and recreated), with the scripted model. No real model calls.

  make -C services/agents-service db-up && uv run python experiments/mailbox_postgres_cost.py
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops_agents.api.app import create_app  # noqa: E402
from ops_agents.api.channels.mailbox.adapter import MailboxAdapter  # noqa: E402
from ops_agents.api.channels.mailbox.fake_graph import FakeMailSource  # noqa: E402
from ops_service_kit.ids import now_iso  # noqa: E402
from ops_service_kit.settings import Settings  # noqa: E402
from tests.conftest import SEED, FakeGraphModels, scripted_model  # noqa: E402

DB = "ops_mailbox_cost"
URL = f"postgresql+asyncpg://ops:ops@localhost:5477/{DB}"
FIXTURE: list[dict[str, Any]] = json.loads((SEED.parent / "mailbox" / "delta_messages.json").read_text())
DEP = "dep_cost"
SAVER_METHODS = ("aget_tuple", "alist", "aput", "aput_writes", "araise_fence")


def out(line: str = "") -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def psql(sql: str) -> None:
    subprocess.run(
        ["docker", "exec", "ops-runtime-postgres-1", "psql", "-U", "ops", "-d", "postgres", "-qc", sql],
        check=True,
        capture_output=True,
    )


def fresh_database() -> None:
    psql(f"DROP DATABASE IF EXISTS {DB}")
    psql(f"CREATE DATABASE {DB}")
    env = {**os.environ, "OPS_DATABASE_URL": URL}
    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True, capture_output=True)


def count_saver_calls(saver: Any, calls: Counter[str]) -> None:
    for name in SAVER_METHODS:
        real: Callable[..., Any] | None = getattr(saver, name, None)
        if real is None:
            continue

        def counted(*args: Any, _real: Callable[..., Any] = real, _name: str = name, **kwargs: Any) -> Any:
            calls[_name] += 1
            return _real(*args, **kwargs)

        setattr(saver, name, counted)


async def measure() -> None:
    engine = create_async_engine(URL)
    statements: Counter[str] = Counter()

    @event.listens_for(engine.sync_engine, "before_cursor_execute")
    def on_statement(*args: Any) -> None:  # pyright: ignore[reportUnusedFunction]
        sql: str = args[2]  # (conn, cursor, statement, parameters, context, executemany)
        statements[sql.split(None, 1)[0].upper()] += 1

    settings = Settings(database_url=URL, seed_dir=SEED, timer_poll_seconds=0, sweep_interval_seconds=3600)
    app = create_app(settings, model=scripted_model(), engine=engine, graph_models=FakeGraphModels())
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://m") as client,
    ):
        rt = app.state.runtime
        saver_calls: Counter[str] = Counter()
        count_saver_calls(rt.saver, saver_calls)
        r = await client.post("/v1/deployments", json={"id": DEP, "graph": "complex_workflow", "channel": "mailbox"})
        r.raise_for_status()
        source = FakeMailSource(FIXTURE)
        adapter = MailboxAdapter(client, source, rt.channels, DEP)
        out(f"PostgreSQL scratch database {DB}, asyncpg checkpointer, scripted model, {len(FIXTURE)} fixture items")
        out("| Run | Items | Cases opened | Messages/s | SQL statements per item | Checkpointer calls per item |")
        out("|---|---|---|---|---|---|")
        for label in ("First poll", "Full replay"):
            if label == "Full replay":
                await rt.channels.save_cursor(DEP, "delta:0", now_iso())  # the whole mailbox again
            statements.clear()
            saver_calls.clear()
            started = time.perf_counter()
            report = await adapter.poll()
            elapsed = time.perf_counter() - started
            items = report.items + report.removed
            out(
                f"| {label} | {items} | {report.new_cases + report.followups} | {items / elapsed:,.0f} "
                f"| {sum(statements.values()) / items:.1f} | {sum(saver_calls.values()) / items:.1f} |"
            )
            out(f"  SQL by verb: {dict(statements.most_common())}")
            out(f"  checkpointer by call: {dict(saver_calls.most_common())}")
    await engine.dispose()


def main() -> None:
    fresh_database()
    asyncio.run(measure())


if __name__ == "__main__":
    main()
