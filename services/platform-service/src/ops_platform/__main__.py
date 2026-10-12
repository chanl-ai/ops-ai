"""`uv run python -m ops_platform`: the public app on settings.platform_port (8710) and the internal app on
settings.platform_internal_port (8711), in one process. The internal port binds to localhost only."""

from __future__ import annotations

import asyncio

import uvicorn

from ops_identity import ServiceAuth, service_verifiers
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings

from .api.app import create_internal_app, create_public_app
from .keys import signer_from
from .seed import seed
from .store.identity import IdentityStore


async def serve(settings: Settings) -> None:
    if settings.environment == "dev":
        await seed(settings.database_url, settings.platform_seed_file)
    store = IdentityStore.open(settings.database_url)
    public = create_public_app(
        store,
        signer_from(settings),
        demo_password=settings.platform_demo_password.get_secret_value() if settings.environment == "dev" else None,
        audiences=settings.platform_audiences,
        cors_origins=settings.cors_origins,
        token_ttl_s=settings.platform_token_ttl_seconds,
    )
    services = ServiceAuth(audience="platform", verifiers=service_verifiers(settings, "platform"), tenant_scoped=False)
    internal = create_internal_app(store, services=services)
    servers = [
        uvicorn.Server(uvicorn.Config(public, host="127.0.0.1", port=settings.platform_port, log_level="info")),
        uvicorn.Server(
            uvicorn.Config(internal, host="127.0.0.1", port=settings.platform_internal_port, log_level="info")
        ),
    ]
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        await store.close()


def main() -> None:
    configure_logging()
    asyncio.run(serve(Settings()))


if __name__ == "__main__":
    main()
