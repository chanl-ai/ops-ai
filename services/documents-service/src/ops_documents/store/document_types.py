# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Document types at rest (c-236): a team's type, its immutable numbered versions (the fields an extraction reads),
its samples (a file and the values it should read), and the test runs of a version over those samples.

Fields, expected values and results are JSON kept as text and never queried (database portability D5). A version is
only ever inserted: saving fields writes version n+1 in the transaction that moves the type's `latest_version`, so a
workflow pinned to version n keeps reading what it was published with."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_contracts.field_values import DEFAULT_DATE_ORDER
from ops_documents.store.metadata import RECOVER_PENDING, ROLE, SYSTEM_ROLE, metadata
from ops_store import isolation
from ops_store.dialect import locked
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.team_scope import any_team, team_visible

TestStatus = Literal["queued", "running", "done", "failed"]

document_types = sa.Table(
    "document_types",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("description", sa.String(1000)),
    sa.Column("latest_version", sa.Integer, nullable=False),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    # A name names one type in its team, so a picker never shows two "Levy notice".
    sa.UniqueConstraint("tenant_id", "team", "name", name="uq_document_types_name"),
    info={**TENANT_SCOPED, **team_owned("team")},
)

document_type_versions = sa.Table(
    "document_type_versions",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("type_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("fields", sa.Text, nullable=False),
    sa.Column("many", sa.Boolean, nullable=False),
    sa.Column("review_below", sa.Float()),
    # MDY or DMY: how the version reads a numeric date such as 03/04/2026 (null on versions before it was a setting).
    sa.Column("date_order", sa.String(3)),
    # Layout templates (c-253), JSON; null on versions saved before, read as none.
    sa.Column("templates", sa.Text),
    # Checks across fields (c-296), JSON; null on versions saved before, read as none.
    sa.Column("checks", sa.Text),
    # Whether reads may show the model the page image (c-295); null on versions saved before, read as off.
    sa.Column("page_images", sa.Boolean),
    # How many checked reads of one layout offer a template (c-254); null on versions saved before, read as the default.
    sa.Column("offer_at", sa.Integer),
    sa.Column("note", sa.String(500)),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    # The type's team, copied when the version is written, so the policy holds it without reading the type (c-415).
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)

document_type_samples = sa.Table(
    "document_type_samples",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("type_id", sa.String(64), nullable=False),
    sa.Column("file_id", sa.String(64), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    # {key: value} for a type reading one record, [{key: value}, ...] in order for a type reading several.
    sa.Column("expected", sa.Text, nullable=False),
    sa.Column("added_by", sa.String(320), nullable=False),
    sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
    sa.Index("ix_document_type_samples_type", "tenant_id", "type_id"),
    sa.Column("team", sa.String(64), nullable=False),
    info={**TENANT_SCOPED, **team_owned("team")},
)

document_type_tests = sa.Table(
    "document_type_tests",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("type_id", sa.String(64), nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("samples", sa.Integer, nullable=False),
    sa.Column("result", sa.Text),
    sa.Column("error", sa.Text),
    sa.Column("asked_by", sa.String(320), nullable=False),
    sa.Column("asked_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Index("ix_document_type_tests_type", "tenant_id", "type_id", "version"),
    sa.Index("ix_document_type_tests_status", "status"),
    info={**TENANT_SCOPED, **team_owned("team")},
)


# A type's examples (c-297): the corrections people made on its reads, as the field, the line its value was printed on
# and the corrected value (JSON). One per read and field; `record` is the record's position, SINGLE for a read of one.
document_type_examples = sa.Table(
    "document_type_examples",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), nullable=False),
    sa.Column("type_id", sa.String(64), nullable=False),
    sa.Column("field", sa.String(128), nullable=False),
    sa.Column("line", sa.Text),
    sa.Column("value", sa.Text, nullable=False),
    sa.Column("extraction_id", sa.String(64), nullable=False),
    sa.Column("record", sa.Integer, nullable=False),
    sa.Column("corrected_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("tenant_id", "extraction_id", "field", "record", name="uq_document_type_examples_read"),
    sa.Index("ix_document_type_examples_type", "tenant_id", "team", "type_id", "created_at"),
    info={**TENANT_SCOPED, **team_owned("team")},
)
# The record of a read of one record, in the examples' unique key (a null would not be unique).
SINGLE = -1
# How many examples of one field a team's type keeps (c-297): a new one drops the oldest past this. Reads are given the
# newest few, so the rest only let a person remove a wrong one without a gap; nothing grows without bound.
EXAMPLES_KEPT_PER_FIELD = 10


def example_view(m: Any) -> dict[str, Any]:
    return {
        "id": m["id"],
        "field": m["field"],
        "line": m["line"],
        "value": json.loads(m["value"]),
        "extractionId": m["extraction_id"],
        "record": None if m["record"] == SINGLE else m["record"],
        "correctedBy": m["corrected_by"],
        "createdAt": m["created_at"].isoformat(),
    }


class NameTakenError(Exception):
    """Another type in the team has this name, or the id is taken."""


def _parsed(m: Any) -> dict[str, Any]:
    """A version row with its JSON columns read."""
    return {
        **dict(m),
        "fields": _json(m["fields"]),
        "templates": _json(m["templates"] or "[]"),
        "checks": _json(m["checks"] or "[]"),
    }


def _json(raw: str | None) -> Any:
    return json.loads(raw) if raw else None


def _type_team(type_id: str) -> Any:
    """The type's team; another team's type is not visible, so a row naming it has no team and is refused."""
    t = document_types
    return sa.select(t.c.team).where(t.c.id == type_id, team_visible(t)).scalar_subquery()


class DocumentTypesStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def create(self, values: Mapping[str, Any], version: Mapping[str, Any]) -> None:
        """The type and its version 1, in one transaction."""
        try:
            async with isolation.isolated_tx(self.engine, role=ROLE) as c:
                await c.execute(sa.insert(document_types).values(**values, latest_version=1))
                await c.execute(sa.insert(document_type_versions).values(**self._version(values, version, 1)))
        except IntegrityError as e:
            raise NameTakenError(str(values["name"])) from e

    async def add_version(self, type_id: str, version: Mapping[str, Any]) -> int:
        """Inserts version latest+1 and moves the type to it; a concurrent save fails on the version key."""
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            head = sa.select(document_types.c.latest_version).where(
                document_types.c.tenant_id == tenant, document_types.c.id == type_id, team_visible(document_types)
            )
            latest = (await c.execute(locked(head, document_types))).scalar_one()
            n = int(latest) + 1
            owner = {"tenant_id": tenant, "id": type_id, "team": _type_team(type_id)}
            await c.execute(sa.insert(document_type_versions).values(**self._version(owner, version, n)))
            await c.execute(
                sa.update(document_types)
                .where(document_types.c.tenant_id == tenant, document_types.c.id == type_id)
                .values(latest_version=n)
            )
        return n

    @staticmethod
    def _version(owner: Mapping[str, Any], version: Mapping[str, Any], n: int) -> dict[str, Any]:
        return {
            "tenant_id": owner["tenant_id"],
            "type_id": owner["id"],
            "team": owner["team"],
            "version": n,
            "fields": json.dumps(version["fields"]),
            "many": bool(version.get("many")),
            "review_below": version.get("review_below"),
            "date_order": version.get("date_order") or DEFAULT_DATE_ORDER,
            "templates": json.dumps(version.get("templates") or []),
            "checks": json.dumps(version.get("checks") or []),
            "page_images": bool(version.get("page_images")),
            "offer_at": version.get("offer_at"),
            "note": version.get("note"),
            "created_by": version["created_by"],
            "created_at": version["created_at"],
        }

    async def get(self, type_id: str) -> dict[str, Any] | None:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (
                (
                    await c.execute(
                        sa.select(document_types).where(
                            document_types.c.tenant_id == tenant,
                            document_types.c.id == type_id,
                            team_visible(document_types),
                        )
                    )
                )
                .mappings()
                .first()
            )
        return dict(m) if m is not None else None

    async def list(self, team: str) -> list[dict[str, Any]]:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(document_types)
                        .where(
                            document_types.c.tenant_id == tenant,
                            document_types.c.team == team,
                            team_visible(document_types),
                        )
                        .order_by(document_types.c.name)
                    )
                )
                .mappings()
                .all()
            )
        return [dict(m) for m in rows]

    async def version(self, type_id: str, n: int) -> dict[str, Any] | None:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (
                (
                    await c.execute(
                        sa.select(document_type_versions).where(
                            document_type_versions.c.tenant_id == tenant,
                            document_type_versions.c.type_id == type_id,
                            document_type_versions.c.version == n,
                            team_visible(document_type_versions),
                        )
                    )
                )
                .mappings()
                .first()
            )
        if m is None:
            return None
        return _parsed(m)

    async def versions(self, type_id: str) -> list[dict[str, Any]]:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(document_type_versions)
                        .where(
                            document_type_versions.c.tenant_id == tenant,
                            document_type_versions.c.type_id == type_id,
                            team_visible(document_type_versions),
                        )
                        .order_by(document_type_versions.c.version.desc())
                    )
                )
                .mappings()
                .all()
            )
        return [_parsed(m) for m in rows]

    async def add_sample(self, values: Mapping[str, Any]) -> None:
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.insert(document_type_samples).values(
                    **{**values, "expected": json.dumps(values["expected"]), "team": _type_team(str(values["type_id"]))}
                )
            )

    async def samples(self, type_id: str) -> list[dict[str, Any]]:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(document_type_samples)
                        .where(
                            document_type_samples.c.tenant_id == tenant,
                            document_type_samples.c.type_id == type_id,
                            team_visible(document_type_samples),
                        )
                        .order_by(document_type_samples.c.added_at, document_type_samples.c.id)
                    )
                )
                .mappings()
                .all()
            )
        return [{**dict(m), "expected": _json(m["expected"])} for m in rows]

    async def remove_sample(self, type_id: str, sample_id: str) -> dict[str, Any] | None:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (
                (
                    await c.execute(
                        sa.delete(document_type_samples)
                        .where(
                            document_type_samples.c.tenant_id == tenant,
                            document_type_samples.c.type_id == type_id,
                            document_type_samples.c.id == sample_id,
                        )
                        .returning(document_type_samples)
                    )
                )
                .mappings()
                .first()
            )
        return dict(m) if m is not None else None

    async def examples(self, team: str, type_id: str) -> list[dict[str, Any]]:
        """The type's examples in the team, newest first (c-297)."""
        tenant = isolation.tenant()
        e = document_type_examples.c
        q = (
            sa.select(document_type_examples)
            .where(e.tenant_id == tenant, e.team == team, e.type_id == type_id, team_visible(document_type_examples))
            .order_by(e.created_at.desc(), e.id.desc())
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            return [example_view(m) for m in (await c.execute(q)).mappings()]

    async def recent_examples(
        self, team: str, type_id: str, fields: list[str], *, per_field: int, total: int
    ) -> list[dict[str, Any]]:
        """What a read of the type is given: for the fields it asks, the newest `per_field` examples of each, newest
        first, at most `total` in all."""
        tenant = isolation.tenant()
        e = document_type_examples.c
        q = (
            sa.select(document_type_examples)
            .where(
                e.tenant_id == tenant,
                e.team == team,
                e.type_id == type_id,
                e.field.in_(fields),
                team_visible(document_type_examples),
            )
            .order_by(e.created_at.desc(), e.id.desc())
        )
        kept: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            for m in (await c.execute(q)).mappings():
                if counts.get(m["field"], 0) >= per_field:
                    continue
                counts[m["field"]] = counts.get(m["field"], 0) + 1
                kept.append(example_view(m))
                if len(kept) >= total:
                    break
        return kept

    async def remove_example(self, team: str, type_id: str, example_id: str) -> bool:
        tenant = isolation.tenant()
        e = document_type_examples.c
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            gone = await c.execute(
                sa.delete(document_type_examples).where(
                    e.tenant_id == tenant, e.team == team, e.type_id == type_id, e.id == example_id
                )
            )
        return bool(gone.rowcount)

    async def insert_test(self, values: Mapping[str, Any]) -> None:
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(sa.insert(document_type_tests).values(**values))

    async def set_test(self, test_id: str, values: Mapping[str, Any]) -> None:
        tenant = isolation.tenant()
        row = dict(values)
        if "result" in row and row["result"] is not None:
            row["result"] = json.dumps(row["result"])
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            await c.execute(
                sa.update(document_type_tests)
                .where(document_type_tests.c.tenant_id == tenant, document_type_tests.c.id == test_id)
                .values(**row)
            )

    async def test(self, test_id: str) -> dict[str, Any] | None:
        tenant = isolation.tenant()
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            m = (
                (
                    await c.execute(
                        sa.select(document_type_tests).where(
                            document_type_tests.c.tenant_id == tenant,
                            document_type_tests.c.id == test_id,
                            team_visible(document_type_tests),
                        )
                    )
                )
                .mappings()
                .first()
            )
        return {**dict(m), "result": _json(m["result"])} if m is not None else None

    async def pending_tests(self) -> list[dict[str, Any]]:
        """Every queued or running test run, across tenants: what a restart picks up again, each then run as its own
        tenant and team."""
        t = document_type_tests
        async with isolation.system_tx(self.engine, RECOVER_PENDING, role=SYSTEM_ROLE) as c:
            rows = (
                (
                    await c.execute(
                        sa.select(t)
                        .where(t.c.status.in_(("queued", "running")), any_team(t, "a restart picks up every team's"))
                        .order_by(document_type_tests.c.asked_at)
                    )
                )
                .mappings()
                .all()
            )
        return [dict(m) for m in rows]

    async def purge_samples(self, team: str, file_id: str) -> int:
        """Removes the samples naming a deleted file on the team's document types; the number removed."""
        tenant = isolation.tenant()
        teams_types = sa.select(document_types.c.id).where(
            document_types.c.tenant_id == tenant, document_types.c.team == team, team_visible(document_types)
        )
        async with isolation.isolated_tx(self.engine, role=ROLE) as c:
            gone = await c.execute(
                sa.delete(document_type_samples).where(
                    document_type_samples.c.tenant_id == tenant,
                    document_type_samples.c.file_id == file_id,
                    document_type_samples.c.type_id.in_(teams_types),
                )
            )
        return int(gone.rowcount or 0)
