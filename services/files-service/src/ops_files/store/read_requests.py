"""Read requests (c-250): a person asks for a file to be read with a document type. The request and its
file.read_requested service event are written in one transaction, so the system extract workflow starts however long
agents-service is down; the relay records the run it started on the request, which the console follows.

A repeat with the same key returns the first request and writes no second event."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_files.store.files import metadata, service_outbox
from ops_store.outbox import add as add_event

read_requests = sa.Table(
    "file_read_requests",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("request_key", sa.String(200), primary_key=True),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("requested_by", sa.String(320), nullable=False),
    # None: read with Detect, which classifies the file over the team's types first (c-335).
    sa.Column("document_type_id", sa.String(64)),
    sa.Column("version", sa.Integer),
    sa.Column("type_name", sa.String(200)),
    # queued until the relay delivers the event; started (with the run) or unhandled after.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_file_read_requests_file", "tenant_id", "file_id"),
)

EVENT = "file.read_requested"


class ReadRequestsStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def request(self, values: Mapping[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
        """The request, new with its event, or the one already holding its key."""
        try:
            async with self.engine.begin() as c:
                await c.execute(sa.insert(read_requests).values(**values, status="queued"))
                await add_event(
                    c,
                    service_outbox,
                    tenant_id=str(values["tenant_id"]),
                    team_id=str(values["team"]),
                    name=EVENT,
                    key=str(values["request_key"]),
                    payload=payload,
                    actor=str(values["requested_by"]),
                )
        except IntegrityError:
            pass
        found = await self.get(str(values["tenant_id"]), str(values["request_key"]))
        assert found is not None
        return found

    async def get(self, tenant: str, key: str) -> dict[str, Any] | None:
        query = sa.select(read_requests).where(read_requests.c.tenant_id == tenant, read_requests.c.request_key == key)
        async with self.engine.connect() as c:
            row = (await c.execute(query)).mappings().first()
        return dict(row) if row is not None else None

    async def started(self, tenant: str, key: str, *, status: str, run_id: str | None) -> None:
        async with self.engine.begin() as c:
            await c.execute(
                sa.update(read_requests)
                .where(read_requests.c.tenant_id == tenant, read_requests.c.request_key == key)
                .values(status=status, run_id=run_id)
            )
