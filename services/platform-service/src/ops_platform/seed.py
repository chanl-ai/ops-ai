"""`uv run python -m ops_platform.seed`: the development tenant, team and people from settings.platform_seed_file,
written to OPS_DATABASE_URL. Every seeded person signs in with the demo password; the people are fictional."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from ops_service_kit.settings import Settings

from .store.seeding import write_seed
from .store.tenancy import TenantDb


async def seed(database_url: str, path: Path) -> None:
    db = TenantDb.open(database_url)
    try:
        await write_seed(db, json.loads(path.read_text()))
    finally:
        await db.engine.dispose()


def main() -> None:
    settings = Settings()
    if settings.environment != "dev":
        raise SystemExit("seed: refusing outside dev; seeded people share one public password")
    asyncio.run(seed(settings.database_url, settings.platform_seed_file))


if __name__ == "__main__":
    main()
