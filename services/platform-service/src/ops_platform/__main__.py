"""`uv run python -m ops_platform`: the public app on settings.platform_port (8710) and the internal app on
settings.platform_internal_port (8711), in one process, both on settings.bind_host. The internal port is never
published: on a host it stays on localhost, in a container only the private network reaches it."""

from __future__ import annotations

import asyncio
from pathlib import Path

import uvicorn

from ops_email import EmailProviders
from ops_identity import ServiceAuth, service_verifiers
from ops_service_kit.logging import configure_logging
from ops_service_kit.settings import Settings
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import run as run_background
from ops_store.schema_version import require_current_schema

from .api.app import create_internal_app, create_public_app
from .keys import signer_from
from .seed import seed
from .signin_options import SignInOptions
from .store.identity import IdentityStore
from .store.lifecycle import LifecycleStore
from .workspace_lifecycle import WorkspacePurge

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"


async def serve(settings: Settings) -> None:
    if settings.environment == "dev":
        await seed(
            settings.database_url,
            settings.platform_seed_file,
            security_team=settings.security_team_id,
            everyone_admin=settings.seed_everyone_admin,
        )
    store = IdentityStore.open(settings.database_url)
    # Reset links go out through the configured mail provider; with none, a reset request says it is not set up.
    mail = EmailProviders.from_settings(settings).sender() if settings.mail_provider != "none" else None
    public = create_public_app(
        store,
        signer_from(settings),
        demo_password=settings.platform_demo_password.get_secret_value() if settings.environment == "dev" else None,
        audiences=settings.platform_audiences,
        dev_people=settings.platform_seed_file if settings.environment == "dev" else None,
        cors_origins=settings.cors_origins,
        token_ttl_s=settings.platform_token_ttl_seconds,
        security_team=settings.security_team_id,
        signin=SignInOptions.from_settings(settings, mail=mail),
    )
    services = ServiceAuth(audience="platform", verifiers=service_verifiers(settings, "platform"), tenant_scoped=False)
    internal = create_internal_app(store, services=services, signer=signer_from(settings))
    servers = [
        uvicorn.Server(uvicorn.Config(public, host=settings.bind_host, port=settings.platform_port, log_level="info")),
        uvicorn.Server(
            uvicorn.Config(internal, host=settings.bind_host, port=settings.platform_internal_port, log_level="info")
        ),
    ]
    # Workspaces closed longer than the restore window are purged here (c-529), one copy for the account.
    purge = WorkspacePurge(
        LifecycleStore(store.db, security_team=settings.security_team_id), restore_days=settings.workspace_restore_days
    )
    stop = asyncio.Event()
    purging = asyncio.create_task(run_background("workspace_lifecycle", purge.once, stop=stop, store=LOCAL_BEATS))
    try:
        await asyncio.gather(*(s.serve() for s in servers))
    finally:
        stop.set()
        await purging
        await store.close()


def main() -> None:
    configure_logging()
    settings = Settings()
    require_current_schema(settings.database_url, MIGRATIONS)
    asyncio.run(serve(settings))


if __name__ == "__main__":
    main()
