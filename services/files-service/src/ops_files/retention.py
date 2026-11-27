"""The retention process: once an hour it deletes released knowledge snapshots whose days have passed (the classes
counted from release) and watched-folder events older than 90 days. Other classes' deletes on their date are planned
and not run here."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from ops_store import background

from .store import WatchesStore
from .tenant_files import TenantFiles

KEY = "files_retention"
# How long a watch keeps what each check found; the entries and their versions follow their own retention.
EVENTS_KEPT = timedelta(days=90)


async def keep_purging(files: TenantFiles, stop: asyncio.Event | None = None, *, every_s: float | None = None) -> None:
    """The listed `files_retention` process, given its pass and run by `background.run_sweep`: one pass an hour (or
    every `every_s`), reported on /health/background. The pass opens its own transactions, a tenant-wide read of
    what is due and then each delete in its own tenant and team, so it is given none."""

    async def purge(_tx: background.Tx, _now: float) -> int:
        # Looked up on each pass, and dated by the files' own clock, as the deletes it makes are.
        swept = await WatchesStore(files.engine).sweep_events(datetime.now(UTC) - EVENTS_KEPT)
        return await files.purge_released() + swept

    background.give_pass(KEY, purge, service="files")
    await background.run_sweep(KEY, stop=stop or asyncio.Event(), every_s=every_s)
