# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Extractions at rest (c-235): one row per extraction, its status kept on the row so a restart picks up what was
queued or running, and one row per checker correction beside the value it corrected.

The request and the answer are JSON kept as text and never queried (database portability D5). `key_hash` is never
null: the SHA-256 of the caller's Idempotency-Key, or of the extraction id when none was sent, so the unique index
dedupes every row (a unique index over a nullable column dedupes nothing for NULL rows)."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, cast

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from ops_documents.store.document_types import EXAMPLES_KEPT_PER_FIELD, document_type_examples
from ops_documents.store.metadata import RECOVER_PENDING, ROLE, SYSTEM_ROLE, metadata
from ops_store import isolation
from ops_store.outbox import add, outbox_table
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.team_scope import any_team, team_visible

Status = Literal["queued", "running", "done", "failed", "unreadable"]
PENDING: tuple[Status, ...] = ("queued", "running")

extractions = sa.Table(
    "extractions",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    # The file's content digest when asked, so a later version of the file is a different extraction.
    sa.Column("file_digest", sa.String(64), nullable=False),
    # {fields, many, ocr, reviewBelow}: everything a re-run after a restart needs, with no caller present.
    sa.Column("request", sa.Text, nullable=False),
    sa.Column("schema_digest", sa.String(64), nullable=False),
    sa.Column("alias", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("outcome", sa.String(16)),  # ok | review, once done
    sa.Column("result", sa.Text),
    sa.Column("error_code", sa.String(64)),
    sa.Column("error", sa.Text),
    sa.Column("attempts", sa.Integer, nullable=False),
    sa.Column("key_hash", sa.String(64), nullable=False),
    sa.Column("request_hash", sa.String(64), nullable=False),
    sa.Column("asked_by", sa.String(320), nullable=False),
    sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    # The document type read with, and the model's measured tokens, so a test estimate prices what reading that type
    # spends rather than a fixed guess (c-247).
    sa.Column("type_id", sa.String(64)),
    sa.Column("input_tokens", sa.Integer),
    sa.Column("output_tokens", sa.Integer),
    # A model read's layout without its values (ops_extract.templates.fingerprint), so template offers group stored
    # values instead of reading every file's layout again (c-254).
    sa.Column("layout_fingerprint", sa.String(32)),
    sa.UniqueConstraint("tenant_id", "key_hash", name="uq_extractions_key"),
    sa.Index("ix_extractions_status", "status"),
    sa.Index("ix_extractions_file", "tenant_id", "file_id"),
    sa.Index("ix_extractions_type_reads", "tenant_id", "team", "type_id", "status", "finished_at"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

# A correction keeps what it replaced, so per-field accuracy can be counted from these rows (c-240).
# Service events documents-service reports (extraction.*), written in the transaction of the change they report and
# relayed to agents-service (c-258's outbox).
service_outbox = outbox_table(metadata, "documents_outbox", info=TENANT_SCOPED)
# A correction's event waits this long before it is sent, and a newer correction of the same extraction replaces it, so
# a person correcting several fields in a row starts one Save data run with the final read, not one per field.
CORRECTION_SETTLE_SECONDS = 5.0
# Reported from the transaction that ends every read (done, unreadable, failed), keyed by the extraction id: a workflow
# step that parked on a long read resumes on it (c-525).
FINISHED_EVENT = "extraction.finished"
SUPERSEDED = "superseded by a newer correction"

extraction_corrections = sa.Table(
    "extraction_corrections",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("tenant_id", sa.String(64), nullable=False),
    sa.Column("extraction_id", sa.String(64), nullable=False),
    sa.Column("field", sa.String(128), nullable=False),
    # The record's position for an extraction of several records; null for a single one.
    sa.Column("record", sa.Integer),
    sa.Column("original", sa.Text, nullable=False),
    sa.Column("original_confidence", sa.Float(), nullable=False),
    sa.Column("corrected", sa.Text, nullable=False),
    sa.Column("corrected_by", sa.String(320), nullable=False),
    sa.Column("corrected_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_extraction_corrections_extraction", "tenant_id", "extraction_id"),
    # The extraction's team, copied when the correction is written (c-415).
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)


@dataclass(frozen=True)
class ExtractionRow:
    id: str
    tenant_id: str
    team: str
    file_id: str
    file_digest: str
    request: dict[str, Any]
    alias: str
    status: Status
    outcome: str | None
    result: dict[str, Any] | None
    error_code: str | None
    error: str | None
    attempts: int
    request_hash: str
    asked_by: str
    asked_at: datetime
    finished_at: datetime | None
    layout_fingerprint: str | None = None


def _row(m: Any) -> ExtractionRow:
    return ExtractionRow(
        id=m["id"],
        tenant_id=m["tenant_id"],
        team=m["team"],
        file_id=m["file_id"],
        file_digest=m["file_digest"],
        request=json.loads(m["request"]),
        alias=m["alias"],
        status=m["status"],
        outcome=m["outcome"],
        result=json.loads(m["result"]) if m["result"] else None,
        error_code=m["error_code"],
        error=m["error"],
        attempts=int(m["attempts"]),
        request_hash=m["request_hash"],
        asked_by=m["asked_by"],
        asked_at=m["asked_at"],
        finished_at=m["finished_at"],
        layout_fingerprint=m.get("layout_fingerprint"),
    )


class ExtractionsStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def insert(self, values: Mapping[str, Any]) -> ExtractionRow:
        """The new row, or the row that already holds its Idempotency-Key (the caller compares request hashes)."""
        row = {**values, "request": json.dumps(values["request"], sort_keys=True)}
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(sa.insert(extractions).values(**row))
        except IntegrityError:
            held = await self._one(
                extractions.c.tenant_id == values["tenant_id"], extractions.c.key_hash == values["key_hash"]
            )
            if held is None:
                raise
            return held
        found = await self.get(str(values["id"]))
        assert found is not None
        return found

    async def held(self, key_hash: str) -> ExtractionRow | None:
        """The extraction an Idempotency-Key already holds, if any."""
        tenant = isolation.tenant()
        return await self._one(extractions.c.tenant_id == tenant, extractions.c.key_hash == key_hash)

    async def get(self, extraction_id: str) -> ExtractionRow | None:
        tenant = isolation.tenant()
        return await self._one(extractions.c.tenant_id == tenant, extractions.c.id == extraction_id)

    async def _one(self, *where: Any) -> ExtractionRow | None:
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (await c.execute(sa.select(extractions).where(*where, team_visible(extractions)))).mappings().first()
        return _row(m) if m is not None else None

    async def start(self, extraction_id: str, at: datetime) -> bool:
        """Marks a queued or running row running and counts the attempt; False when it is already finished."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            done = await c.execute(
                sa.update(extractions)
                .where(
                    extractions.c.tenant_id == tenant,
                    extractions.c.id == extraction_id,
                    extractions.c.status.in_(PENDING),
                )
                .values(status="running", attempts=extractions.c.attempts + 1, started_at=at)
            )
        return done.rowcount == 1

    async def requeue(self, extraction_id: str) -> ExtractionRow:
        """A failed extraction queued again, its error cleared, for a retry under the same Idempotency-Key."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(extractions)
                .where(extractions.c.tenant_id == tenant, extractions.c.id == extraction_id)
                .values(status="queued", error_code=None, error=None, result=None, outcome=None, finished_at=None)
            )
        found = await self.get(extraction_id)
        assert found is not None
        return found

    async def finish(
        self,
        extraction_id: str,
        *,
        status: Status,
        at: datetime,
        outcome: str | None = None,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error: str | None = None,
        tokens: tuple[int, int] | None = None,
        fingerprint: str | None = None,
    ) -> None:
        tenant = isolation.tenant()
        values: dict[str, Any] = {
            "status": status,
            "outcome": outcome,
            "result": json.dumps(result) if result is not None else None,
            "error_code": error_code,
            "error": error,
            "finished_at": at,
        }
        if tokens is not None:
            values |= {"input_tokens": tokens[0], "output_tokens": tokens[1]}
        if fingerprint is not None:
            values["layout_fingerprint"] = fingerprint
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(extractions)
                .where(extractions.c.tenant_id == tenant, extractions.c.id == extraction_id)
                .values(**values)
            )
            e = extractions
            q = sa.select(e.c.team, e.c.file_id, e.c.type_id, e.c.asked_by).where(
                e.c.tenant_id == tenant, e.c.id == extraction_id
            )
            row = (await c.execute(q)).first()
            if row is not None:
                review = cast(list[Any], (result or {}).get("needsReview") or [])
                payload = {
                    "extractionId": extraction_id,
                    "fileId": row.file_id,
                    "status": status,
                    "outcome": outcome,
                    "documentType": row.type_id,
                    "needsReview": len(review),
                    "errorCode": error_code,
                }
                await add(
                    c, service_outbox, tenant_id=tenant, team_id=row.team, name=FINISHED_EVENT,
                    key=extraction_id, payload=payload, actor=row.asked_by,
                )  # fmt: skip

    async def tokens_per_call(self, type_id: str | None, *, last: int = 20) -> tuple[float, float] | None:
        """The mean input and output tokens of the tenant's last `last` measured extractions, of one document type when
        `type_id` is given; None when there are none yet."""
        tenant = isolation.tenant()
        where = [extractions.c.tenant_id == tenant, extractions.c.output_tokens.is_not(None)]
        if type_id is not None:
            where.append(extractions.c.type_id == type_id)
        recent = (
            sa.select(extractions.c.input_tokens, extractions.c.output_tokens)
            .where(*where, team_visible(extractions))
            .order_by(extractions.c.finished_at.desc())
            .limit(last)
            .subquery()
        )
        query = sa.select(sa.func.count(), sa.func.avg(recent.c.input_tokens), sa.func.avg(recent.c.output_tokens))
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            count, tokens_in, tokens_out = (await c.execute(query)).one()
        return (float(tokens_in), float(tokens_out)) if count else None

    async def recent_reads(self, team: str, type_id: str, *, last: int) -> list[ExtractionRow]:
        """The team's last `last` finished reads of a document type, newest first (c-254's template offers)."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(extractions)
                        .where(
                            extractions.c.tenant_id == tenant,
                            extractions.c.team == team,
                            extractions.c.type_id == type_id,
                            extractions.c.status == "done",
                            team_visible(extractions),
                        )
                        .order_by(extractions.c.finished_at.desc())
                        .limit(last)
                    )
                )
                .mappings()
                .all()
            )
        return [_row(m) for m in rows]

    async def keep_fingerprint(self, extraction_id: str, fingerprint: str) -> None:
        """A read saved before fingerprints were stored gets its own once (c-254)."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(extractions)
                .where(extractions.c.tenant_id == tenant, extractions.c.id == extraction_id)
                .values(layout_fingerprint=fingerprint)
            )

    async def pending(self) -> list[ExtractionRow]:
        """Every queued or running extraction, across tenants: what a restart picks up again, each then read as its
        own tenant and team."""
        t = extractions
        async with isolation.system_tx(self.engine, RECOVER_PENDING, role=SYSTEM_ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(t)
                        .where(t.c.status.in_(PENDING), any_team(t, "a restart picks up every team's"))
                        .order_by(extractions.c.asked_at)
                    )
                )
                .mappings()
                .all()
            )
        return [_row(m) for m in rows]

    async def for_file(self, team: str, file_id: str, *, offset: int, limit: int) -> tuple[list[ExtractionRow], int]:
        """One page of the team's extractions of one file, newest first, and how many there are."""
        tenant = isolation.tenant()
        where = (extractions.c.tenant_id == tenant, extractions.c.team == team, extractions.c.file_id == file_id)
        query = (
            sa.select(extractions)
            .where(*where, team_visible(extractions))
            .order_by(extractions.c.asked_at.desc(), extractions.c.id)
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (await c.execute(query.offset(offset).limit(limit))).mappings().all()
            total = int(
                (
                    await c.execute(
                        sa.select(sa.func.count()).select_from(extractions).where(*where, team_visible(extractions))
                    )
                ).scalar_one()
            )
        return [_row(m) for m in rows], total

    async def correct(
        self,
        values: Mapping[str, Any],
        result: dict[str, Any],
        *,
        event: Mapping[str, Any] | None = None,
        example: Mapping[str, Any] | None = None,
    ) -> None:
        """Records a correction and writes the extraction's answer with the corrected value, its event when given, and
        the example it teaches its document type (c-297), in one transaction."""
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            if example is not None:
                await _keep_example(c, example)
            if event is not None:
                now = time.time()
                o = service_outbox
                await c.execute(
                    o.update()
                    .where(
                        o.c.tenant_id == event["tenant_id"],
                        o.c.name == event["name"],
                        o.c.event_key.like(f"{values['extraction_id']}:%"),
                        o.c.sent_at.is_(None),
                    )
                    # Never sent and never due again: a superseded event must not look delivered.
                    .values(next_at=None, last_error=SUPERSEDED)
                )
                await add(c, service_outbox, **event, now=now, due_at=now + CORRECTION_SETTLE_SECONDS)
            await c.execute(
                sa.insert(extraction_corrections).values(
                    **{
                        **values,
                        "original": json.dumps(values["original"]),
                        "corrected": json.dumps(values["corrected"]),
                        "team": sa.select(extractions.c.team)
                        .where(extractions.c.id == values["extraction_id"], team_visible(extractions))
                        .scalar_subquery(),
                    }
                )
            )
            await c.execute(
                sa.update(extractions)
                .where(extractions.c.tenant_id == values["tenant_id"], extractions.c.id == values["extraction_id"])
                .values(result=json.dumps(result))
            )

    async def corrections(self, extraction_id: str) -> list[dict[str, Any]]:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(extraction_corrections)
                        .where(
                            extraction_corrections.c.tenant_id == tenant,
                            extraction_corrections.c.extraction_id == extraction_id,
                            team_visible(extraction_corrections),
                        )
                        .order_by(extraction_corrections.c.id)
                    )
                )
                .mappings()
                .all()
            )
        return [
            {
                "field": m["field"],
                "record": m["record"],
                "original": json.loads(m["original"]),
                "originalConfidence": m["original_confidence"],
                "corrected": json.loads(m["corrected"]),
                "correctedBy": m["corrected_by"],
                "correctedAt": m["corrected_at"].isoformat(),
            }
            for m in rows
        ]

    async def purge(self, team: str, file_id: str) -> int:
        """Removes the team's extractions of a deleted file, their corrections and the examples those taught; the number
        of extractions removed.
        Another team's reads of the file are its own purge's to remove."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            ids = [
                r[0]
                for r in await c.execute(
                    sa.select(extractions.c.id).where(
                        extractions.c.tenant_id == tenant,
                        extractions.c.team == team,
                        extractions.c.file_id == file_id,
                        team_visible(extractions),
                    )
                )
            ]
            if ids:
                # A deleted file's printed lines leave with it, in the examples its corrections taught too.
                await c.execute(
                    sa.delete(document_type_examples).where(
                        document_type_examples.c.tenant_id == tenant, document_type_examples.c.extraction_id.in_(ids)
                    )
                )
                await c.execute(
                    sa.delete(extraction_corrections).where(
                        extraction_corrections.c.tenant_id == tenant, extraction_corrections.c.extraction_id.in_(ids)
                    )
                )
                await c.execute(
                    sa.delete(extractions).where(extractions.c.tenant_id == tenant, extractions.c.id.in_(ids))
                )
        return len(ids)


async def _keep_example(c: AsyncConnection, example: Mapping[str, Any]) -> None:
    """The example a correction teaches (c-297): it replaces the one the same read's field taught before, and adds
    nothing when another read of the type already taught the same field, line and value."""
    e = document_type_examples.c
    value = json.dumps(example["value"], sort_keys=True)
    await c.execute(
        sa.delete(document_type_examples).where(
            e.tenant_id == example["tenant_id"],
            e.extraction_id == example["extraction_id"],
            e.field == example["field"],
            e.record == example["record"],
        )
    )
    line = e.line.is_(None) if example["line"] is None else e.line == example["line"]
    taught = (
        await c.execute(
            sa.select(e.id).where(
                e.tenant_id == example["tenant_id"],
                e.team == example["team"],
                e.type_id == example["type_id"],
                e.field == example["field"],
                line,
                e.value == value,
                team_visible(document_type_examples),
            )
        )
    ).first()
    if taught is None:
        await c.execute(sa.insert(document_type_examples).values(**{**example, "value": value}))
    same = (
        e.tenant_id == example["tenant_id"],
        e.team == example["team"],
        e.type_id == example["type_id"],
        e.field == example["field"],
    )
    newest = sa.select(e.id).where(*same).order_by(e.created_at.desc(), e.id.desc()).limit(EXAMPLES_KEPT_PER_FIELD)
    kept = [r[0] for r in await c.execute(newest)]
    await c.execute(sa.delete(document_type_examples).where(*same, e.id.not_in(kept)))
