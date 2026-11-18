"""Read requests: a person asks for a file to be read with a document type. The request and its
file.read_requested service event are written in one transaction, so the system extract workflow starts however long
agents-service is down; the relay records the run it started on the request, which the console follows.

A repeat with the same key returns the first request and writes no second event."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal, TypedDict

import sqlalchemy as sa
from pydantic import JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_files.store.files import ROLE, metadata, service_outbox
from ops_service_kit.http import Out
from ops_store import isolation
from ops_store.outbox import add as add_event
from ops_store.rows import one
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.store import Store
from ops_store.team_scope import team_visible

read_requests = sa.Table(
    "file_read_requests",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("request_key", sa.String(200), primary_key=True),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("requested_by", sa.String(320), nullable=False),
    # None: read with Detect, which classifies the file over the team's types first.
    sa.Column("document_type_id", sa.String(64)),
    sa.Column("version", sa.Integer),
    sa.Column("type_name", sa.String(200)),
    # queued until the relay delivers the event; started (with the run) or unhandled after.
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("run_id", sa.String(64)),
    sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_file_read_requests_file", "tenant_id", "file_id"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

EVENT = "file.read_requested"


class NewReadRequest(TypedDict):
    """The columns of a read request row; its status starts as queued."""

    tenant_id: str
    request_key: str
    file_id: str
    team: str
    requested_by: str
    document_type_id: str | None
    version: int | None
    type_name: str | None
    requested_at: datetime


class ReadRequestedPayload(TypedDict):
    """The body of the file.read_requested event, in its wire keys."""

    fileId: str
    fileName: str
    documentTypeId: str | None
    version: int | None
    typeName: str | None
    read: Literal["fields", "propose"] | None
    hint: str | None
    maxPages: int | None


class ReadRequestRow(Out):
    tenant_id: str
    request_key: str
    file_id: str
    team: str
    requested_by: str
    document_type_id: str | None
    version: int | None
    type_name: str | None
    status: Literal["queued", "started", "unhandled"]
    run_id: str | None
    requested_at: datetime


class ReadRequestsStore(Store):
    role = ROLE

    async def request(self, values: NewReadRequest, payload: ReadRequestedPayload) -> ReadRequestRow:
        """The request, new with its event, or the one already holding its key."""
        key = values["request_key"]
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await c.execute(sa.insert(read_requests).values(**values, status="queued"))
                    await add_event(
                        c,
                        service_outbox,
                        tenant_id=values["tenant_id"],
                        team_id=values["team"],
                        name=EVENT,
                        key=key,
                        payload=dict(payload),
                        actor=values["requested_by"],
                    )
            except IntegrityError:
                pass
            found = await self._get(c, key)
        assert found is not None
        return found

    async def get(self, key: str) -> ReadRequestRow | None:
        async with self.tx() as c:
            return await self._get(c, key)

    @staticmethod
    async def _get(c: AsyncConnection, key: str) -> ReadRequestRow | None:
        t = read_requests
        query = sa.select(t).where(t.c.tenant_id == isolation.tenant(), t.c.request_key == key, team_visible(t))
        return await one(c, query, ReadRequestRow)

    async def started(self, key: str, *, status: str, run_id: str | None) -> None:
        tenant = isolation.tenant()
        async with self.tx() as c:
            await c.execute(
                sa.update(read_requests)
                .where(read_requests.c.tenant_id == tenant, read_requests.c.request_key == key)
                .values(status=status, run_id=run_id)
            )

    async def record_run(self, body: Mapping[str, JsonValue], service: str, answer: JsonValue) -> None:
        """The relay's `enrich`: a delivered read request's event names the run agents-service started, recorded on
        the request so the console follows it. Runs inside the event's tenant and team. `answer` is agents-service's
        reply JSON, which this service does not define."""
        if body["name"] != EVENT or service != "agents" or not isinstance(answer, dict):
            return
        runs = answer.get("runIds") or []
        first = runs[0] if isinstance(runs, list) and runs else None
        await self.started(
            str(body["key"]), status=str(answer.get("status")), run_id=None if first is None else str(first)
        )
