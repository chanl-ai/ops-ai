"""`uv run python -m ops_models`: models-service on settings.models_port (8730), seeded in development."""

from __future__ import annotations

import asyncio

import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from ops_identity import Auth
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings

from .app import create_models_app
from .seed import seed


async def _seed(engine: AsyncEngine) -> None:
    """Seeds on this short-lived loop, then empties the pool: its connections belong to this loop, and uvicorn serves
    on another, where reusing one fails with "attached to a different loop"."""
    await seed(engine)
    await engine.dispose()


def main() -> None:
    settings = Settings()
    configure_logging()
    engine = create_async_engine(settings.database_url)
    if settings.environment == "dev":
        asyncio.run(_seed(engine))
    app = create_models_app(
        engine,
        auth=Auth.from_settings(settings, audience="models"),
        provider_secrets={k: v.get_secret_value() for k, v in settings.model_provider_keys.items()},
        overlap_seconds=settings.model_key_overlap_seconds,
    )
    uvicorn.run(app, host="127.0.0.1", port=settings.models_port, log_level="info")


if __name__ == "__main__":
    main()
