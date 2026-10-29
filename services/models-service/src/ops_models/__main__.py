"""`uv run python -m ops_models`: models-service on settings.models_port (8730), seeded in development."""

from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn

from ops_identity import Auth
from ops_policy import AesGcmCipher
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings, require_keys
from ops_store.database import Database, open_database
from ops_store.schema_version import require_current_schema

from .app import create_models_app
from .seed import seed

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


async def _seed(engine: Database, fake_openai_url: str | None) -> None:
    """Seeds on this short-lived loop, then empties the pool: its connections belong to this loop, and uvicorn serves
    on another, where reusing one fails with "attached to a different loop"."""
    await seed(engine, fake_openai_url)
    await engine.dispose()


def dev_provider_keys(settings: Settings) -> dict[str, str]:
    """The dev stack's provider keys from settings, behind the ones an account admin saves. Outside dev a key still in
    settings stops start-up, naming the key to save on Settings > Model providers instead."""
    in_settings = {k: v.get_secret_value() for k, v in settings.model_provider_keys.items()}
    if in_settings and settings.environment != "dev":
        names = ", ".join(sorted(in_settings))
        raise SystemExit(
            f"Model provider keys are saved on Settings > Model providers: add {names} there and unset "
            "OPS_MODEL_PROVIDER_KEYS."
        )
    return in_settings


def main() -> None:
    settings = Settings()
    # Provider keys are sealed with it: the public dev default would let anyone with the database read them.
    require_keys(settings, "secrets_key")
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging()
    engine = open_database(settings.database_url)
    if settings.environment == "dev":
        asyncio.run(_seed(engine, settings.models_fake_openai_url))
    app = create_models_app(
        engine,
        auth=Auth.from_settings(settings, audience="models"),
        provider_secrets=dev_provider_keys(settings),
        cipher=AesGcmCipher(settings.secrets_key.get_secret_value()),
        keys_tenant=settings.model_keys_tenant,
        security_team=settings.security_team_id,
        overlap_seconds=settings.model_key_overlap_seconds,
    )
    uvicorn.run(app, host=settings.bind_host, port=settings.models_port, log_level="info")


if __name__ == "__main__":
    main()
