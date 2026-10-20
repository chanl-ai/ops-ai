"""`python -m ops_agents.api`: builds Settings once at boot (a bad value stops the process) and serves."""

from __future__ import annotations

from pathlib import Path

import uvicorn

from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings, require_keys
from ops_store.schema_version import require_current_schema

from .app import create_app

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"


def main() -> None:
    configure_logging()
    settings = Settings()
    require_keys(settings, "review_key")
    require_current_schema(settings.database_url, MIGRATIONS)
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
