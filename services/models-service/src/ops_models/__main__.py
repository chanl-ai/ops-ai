"""`uv run python -m ops_models`: models-service on settings.models_port (8730), seeded in development."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import uvicorn

from ops_identity import Auth, ServiceClient
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings
from ops_store.database import Database, open_database
from ops_store.schema_version import require_current_schema

from .app import create_models_app
from .provider_keys import ProviderKeys
from .seed import seed

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


async def _seed(engine: Database, fake_openai_url: str | None) -> None:
    """Seeds on this short-lived loop, then empties the pool: its connections belong to this loop, and uvicorn serves
    on another, where reusing one fails with "attached to a different loop"."""
    await seed(engine, fake_openai_url)
    await engine.dispose()


def provider_keys(settings: Settings) -> ProviderKeys:
    """Keys from the Secrets store of the deployment's tenant (c-177), read through tools-service; outside dev a key
    still in settings stops start-up, naming the Secrets entry to create instead (c-221)."""
    in_settings = {k: v.get_secret_value() for k, v in settings.model_provider_keys.items()}
    if in_settings and settings.environment != "dev":
        names = ", ".join(sorted(in_settings))
        raise SystemExit(
            f"Model provider keys are read from Secrets: add {names} there and unset OPS_MODEL_PROVIDER_KEYS."
        )
    tools = settings.tools_url or settings.gateway_url
    secrets = (
        ServiceClient.for_settings(
            settings,
            httpx.AsyncClient(base_url=tools, timeout=5),
            service="models",
            audience="tools",
            scopes=["secrets_egress:run"],
            tenant=lambda: settings.model_keys_tenant,
            timeout=5,
        )
        if tools
        else None
    )
    return ProviderKeys(secrets, in_settings)


def main() -> None:
    settings = Settings()
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging()
    engine = open_database(settings.database_url)
    if settings.environment == "dev":
        asyncio.run(_seed(engine, settings.models_fake_openai_url))
    app = create_models_app(
        engine,
        auth=Auth.from_settings(settings, audience="models"),
        provider_keys=provider_keys(settings),
        overlap_seconds=settings.model_key_overlap_seconds,
    )
    uvicorn.run(app, host=settings.bind_host, port=settings.models_port, log_level="info")


if __name__ == "__main__":
    main()
