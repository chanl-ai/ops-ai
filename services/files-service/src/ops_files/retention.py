"""The retention process: once a day it deletes released knowledge snapshots whose days have passed (the classes
counted from release). Other classes' deletes on their date are planned and not run here."""

from __future__ import annotations

import asyncio

from ops_store import background

from .tenant_files import TenantFiles

EVERY_S = 3600.0


async def keep_purging(files: TenantFiles, stop: asyncio.Event | None = None) -> None:
    """The listed `files_retention` process: one pass an hour through the shared runner, reported on
    /health/background."""

    async def once() -> int:
        return await files.purge_released()

    await background.run("files_retention", once, stop=stop or asyncio.Event(), store=background.LOCAL)
