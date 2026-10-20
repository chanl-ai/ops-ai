# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Layouts at rest (c-247): one per tenant, file content digest, layout engine version and OCR choice, so the same
bytes are read once and a change to how layouts are built reads them again. The layout is JSON kept as text and never
queried (database portability D5)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_documents.store.metadata import metadata

documents_layouts = sa.Table(
    "documents_layouts",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("file_digest", sa.String(64), primary_key=True),
    sa.Column("engine", sa.String(32), primary_key=True),
    # A layout read without OCR lists a scan's pages with no text; one read with OCR is a different layout.
    sa.Column("ocr", sa.Boolean, primary_key=True),
    sa.Column("pages", sa.Integer, nullable=False),
    sa.Column("layout", sa.Text, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)


class LayoutsStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def get(self, tenant: str, digest: str, engine: str, *, ocr: bool) -> dict[str, Any] | None:
        query = sa.select(documents_layouts.c.layout).where(
            documents_layouts.c.tenant_id == tenant,
            documents_layouts.c.file_digest == digest,
            documents_layouts.c.engine == engine,
            documents_layouts.c.ocr == ocr,
        )
        async with self.engine.connect() as c:
            text = (await c.execute(query)).scalar_one_or_none()
        return json.loads(text) if text is not None else None

    async def put(
        self, tenant: str, digest: str, engine: str, *, ocr: bool, layout: dict[str, Any], at: datetime
    ) -> None:
        """Keeps the layout; two readers of the same bytes racing keep the first, which is the same layout."""
        row = {
            "tenant_id": tenant,
            "file_digest": digest,
            "engine": engine,
            "ocr": ocr,
            "pages": len(layout["pages"]),
            "layout": json.dumps(layout),
            "created_at": at,
        }
        try:
            async with self.engine.begin() as c:
                await c.execute(sa.insert(documents_layouts).values(**row))
        except IntegrityError:
            return
