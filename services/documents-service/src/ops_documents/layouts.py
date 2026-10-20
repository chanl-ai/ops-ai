# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""A file's layout (c-247), read once per tenant, content digest, layout engine version and OCR choice, and cached:
extraction, highlights, templates and classify all read this one parse. Bytes come through files-service as the
caller's team, so a file the team cannot see has no layout (FileMissingError)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ops_documents.files import Files, Who
from ops_documents.store import LayoutsStore
from ops_extract.layout import ENGINE, Layout, build_layout
from ops_files_client import FileInfo

# ENGINE and build_layout are re-exported for the tests that swap them.
__all__ = ["ENGINE", "Layouts", "build_layout", "page_of"]


@dataclass
class Layouts:
    files: Files
    store: LayoutsStore | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def of(self, who: Who, file: FileInfo, *, ocr: bool) -> Layout:
        """The cached layout of the file's bytes, read and kept on the first ask. A file with no digest yet is read
        each time, since nothing identifies its bytes."""
        if self.store is not None and file.digest:
            cached = await self.store.get(who.tenant_id, file.digest, ENGINE, ocr=ocr)
            if cached is not None:
                return cached
        data = await self.files.read(who, file)
        layout = await asyncio.to_thread(build_layout, data, filename=file.name, mime=file.mime, ocr=ocr)
        if self.store is not None and file.digest:
            await self.store.put(who.tenant_id, file.digest, ENGINE, ocr=ocr, layout=layout, at=self.clock())
        return layout

    async def compute(self, who: Who, file_id: str, *, ocr: bool) -> Layout:
        return await self.of(who, await self.files.readable(who, file_id), ocr=ocr)

    async def cached(self, who: Who, file_id: str, *, ocr: bool) -> Layout | None:
        """The layout already read for the file, without reading it; None when it was never asked for."""
        file = await self.files.readable(who, file_id)
        if self.store is None or not file.digest:
            return None
        return await self.store.get(who.tenant_id, file.digest, ENGINE, ocr=ocr)


def page_of(layout: Layout, page: int) -> dict[str, Any]:
    """One page of a layout: its page entry, blocks and words."""
    return {
        "engine": layout["engine"],
        "pages": [p for p in layout["pages"] if p["number"] == page],
        "blocks": [b for b in layout["blocks"] if b["page"] == page],
        "words": [w for w in layout["words"] if w["page"] == page],
    }
