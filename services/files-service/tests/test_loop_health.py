"""files-service's background processes, as its lifespan runs them: a pass that raises shows on /health/background,
so a relay, a retention loop or the watched-folder checks that have stopped working never read as running."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.app import create_files_app
from ops_files.retention import keep_purging
from ops_files.store import FilesStore
from ops_files.tenant_files import TenantFiles
from ops_files.watches import WatchChecks, keep_checking
from ops_identity import Auth
from ops_service_kit.settings import Settings
from ops_storage.local import LocalObjectStore
from ops_store.outbox import Relay, run_relay
from ops_store.testing import loop_reports_failure
from tests.test_api import CONFIG
from tests.test_file_events import Agents, files_relay

Loop = Callable[[], Coroutine[Any, Any, None]]


@asynccontextmanager
async def serving(files: TenantFiles, loop: Loop, key: str) -> AsyncGenerator[httpx.AsyncClient]:
    """The files app with `loop` started by its lifespan, once the loop's first heartbeat is on the report."""
    auth = Auth.for_dev(Settings(), audience="files", name="james", email="james@harborpine.example", tenant_id="t")
    app = create_files_app(files, engine=files.engine, auth=auth, background=[loop])
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://files")
    async with app.router.lifespan_context(app), http as client:
        for _ in range(100):
            listed = (await client.get("/health/background")).json()["processes"]
            if any(p["key"] == key and p["lastRunAt"] for p in listed):
                break
            await asyncio.sleep(0.05)
        yield client


def _files(engine: AsyncEngine, tmp_path: Path) -> TenantFiles:
    return TenantFiles(LocalObjectStore(tmp_path / "objects", signing_key=b"k" * 32), FilesStore(engine), CONFIG)


async def test_a_relay_pass_that_raises_shows_on_health(engine: AsyncEngine, tmp_path: Path) -> None:
    files = _files(engine, tmp_path)
    relay: Relay = files_relay(engine, Agents())
    stop = asyncio.Event()

    async def broken() -> int:
        raise ConnectionError("outbox unreachable")

    async with serving(files, lambda: run_relay(relay, key="files_relay", stop=stop), "files_relay") as client:
        await loop_reports_failure(client, "files_relay", lambda: setattr(relay, "once", broken))
    stop.set()


async def test_a_retention_pass_that_raises_shows_on_health(engine: AsyncEngine, tmp_path: Path) -> None:
    files = _files(engine, tmp_path)
    stop = asyncio.Event()

    async def broken(*_: object) -> int:
        raise ConnectionError("database connection refused")

    async def loop() -> None:
        await keep_purging(files, stop, every_s=0.05)

    async with serving(files, loop, "files_retention") as client:
        await loop_reports_failure(client, "files_retention", lambda: setattr(files, "purge_released", broken))
    stop.set()


async def test_a_watch_check_pass_that_raises_shows_on_health(engine: AsyncEngine, tmp_path: Path) -> None:
    files = _files(engine, tmp_path)
    checks = WatchChecks(files, reader=None)  # pyright: ignore[reportArgumentType]  # the broken pass reads nothing
    stop = asyncio.Event()

    async def broken() -> int:
        raise ConnectionError("database connection refused")

    async def loop() -> None:
        await keep_checking(checks, stop, every_s=0.05)

    async with serving(files, loop, "files_watch_checks") as client:
        await loop_reports_failure(client, "files_watch_checks", lambda: setattr(checks, "run_asked", broken))
    stop.set()
