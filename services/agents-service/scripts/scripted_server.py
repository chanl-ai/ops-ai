# pyright: reportMissingTypeStubs=false, reportUnknownMemberType=false, reportUnknownVariableType=false
# asyncpg ships without type information; it is used here only to create the database.
"""The agents service on the scripted model: the real app, routers and PostgreSQL, with no provider behind it.

  uv run python scripts/scripted_server.py --port 8790 --db ops_usecase [--cors http://localhost:3018]
  uv run python scripts/scripted_server.py --port 0 --db ops_usecase --migrate-only   # for the tools service

Use cases (docs/usecases/) start this instead of `make run-agents`, so a use case drives the real HTTP surface and
never makes a model call. The scripted chat model and the fake workflow models are the test suite's
(tests/conftest.py); a use case and a unit test therefore see the same replies for the same input. The database is
created and migrated on start, so each use case run owns its tables and leaves the dev database alone.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import uvicorn
from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops_agents.api.app import create_app  # noqa: E402
from ops_service_kit.logging import configure_logging  # noqa: E402
from ops_service_kit.settings import Settings  # noqa: E402
from tests.conftest import SEED, FakeGraphModels, scripted_model  # noqa: E402


def pg_url(db: str, driver: str = "postgresql+asyncpg") -> str:
    """make/env.mk's rule: the devcontainer's side container (OPS_INFRA=external), else compose on OPS_PG_PORT."""
    if os.environ.get("OPS_INFRA") == "external":
        return f"{driver}://ops:ops@postgres:5432/{db}"
    return f"{driver}://ops:ops@localhost:{os.environ.get('OPS_PG_PORT', '5477')}/{db}"


async def ensure_database(name: str) -> None:
    conn = await asyncpg.connect(pg_url("postgres", "postgresql"))
    try:
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--db", required=True)
    p.add_argument("--cors", action="append", default=[])
    p.add_argument("--gateway-url")
    p.add_argument("--timer-poll-seconds", type=float, default=0.0)
    p.add_argument("--migrate-only", action="store_true", help="create and migrate the database, then exit")
    args = p.parse_args()

    url = pg_url(args.db)
    # Settings is the one place env is read, so the URL reaches both Alembic and the app through it.
    os.environ["OPS_DATABASE_URL"] = url
    asyncio.run(ensure_database(args.db))
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    if args.migrate_only:
        return

    settings = Settings(
        database_url=url,
        port=args.port,
        seed_dir=SEED,
        gateway_url=args.gateway_url,
        cors_origins=args.cors or ["http://localhost:3016"],
        timer_poll_seconds=args.timer_poll_seconds,
    )
    configure_logging()
    # With OPS_MODELS_URL and OPS_MODELS_KEY in the environment, turns go to models-service, whose dev seed answers
    # every alias with its scripted provider; still no provider call.
    through_models = settings.models_url is not None and settings.models_key is not None
    app = create_app(settings, model=None if through_models else scripted_model(), graph_models=FakeGraphModels())
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
