"""`uv run python -m ops_kb`: kb-service on settings.kb_port (8740)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import uvicorn

from ops_identity import Auth
from ops_service_kit.logging import configure_logging, get_logger
from ops_service_kit.settings import Settings
from ops_store.schema_version import require_current_schema

from .agents import StaticAgents
from .app import create_kb_app
from .files import KnowledgeFiles, file_intake, move_files
from .seed import seed_demo
from .service import KnowledgeService, source_team
from .store import KnowledgeStore, engine_for
from .store.fulltext import PostgresFullTextRetriever

# This service's own migration chain: it starts only on a database that records the chain's head.
MIGRATIONS = Path(__file__).resolve().parents[2] / "migrations"

log = get_logger(__name__)


async def _seed(settings: Settings) -> None:
    """The demo's two knowledge bases, in dev only; "used by" is not read while seeding, so no agents call is made."""
    engine = engine_for(settings.database_url)
    service = KnowledgeService(
        KnowledgeStore(engine), file_intake(settings), PostgresFullTextRetriever(engine), StaticAgents()
    )
    try:
        await _files_ready(settings)
        if settings.files_url:
            await move_to_files_service(service, KnowledgeFiles(settings.kb_files_dir))
        await seed_demo(service)
    except Exception:
        # A demo base that cannot be made must not stop the service starting; the log says which and why.
        log.exception("demo_knowledge_seed_failed")
    finally:
        await engine.dispose()


async def move_to_files_service(
    service: KnowledgeService, old: KnowledgeFiles, tenants: list[str] | None = None
) -> None:
    """A stack that kept files in kb-service's own store and now uses files-service: each source's files the old
    store holds are copied into files-service and the source points at the copies, so its documents keep syncing."""
    for tenant in tenants if tenants is not None else await service.store.tenants():
        for s in await service.store.sources(tenant):
            names: dict[str, str] = s.get("file_names") or {}
            moved = await move_files(tenant, source_team(s), list(s["file_ids"]), names, to=service.files, old=old)
            if moved:
                await service.store.swap_files(tenant, str(s["id"]), moved)
                log.info("kb_files_moved_to_files_service", source=s["id"], files=len(moved))


async def _files_ready(settings: Settings) -> None:
    """The stack starts files-service just before kb-service; the seed uploads through it, so wait up to a minute."""
    if not settings.files_url:
        return
    async with httpx.AsyncClient(base_url=settings.files_url, timeout=2) as http:
        for _ in range(60):
            try:
                if (await http.get("/health")).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(1)
    log.warning("files_service_not_ready", url=settings.files_url)


def main() -> None:
    settings = Settings()
    require_current_schema(settings.database_url, MIGRATIONS)
    configure_logging()
    if settings.environment == "dev":
        asyncio.run(_seed(settings))
    app = create_kb_app(engine_for(settings.database_url), auth=Auth.from_settings(settings, audience="kb"))
    uvicorn.run(app, host=settings.bind_host, port=settings.kb_port, log_level="info")


if __name__ == "__main__":
    main()
