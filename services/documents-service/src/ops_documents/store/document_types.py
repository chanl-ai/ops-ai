# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Document types at rest: a team's type, its immutable numbered versions (the fields an extraction reads),
its samples (a file and the values it should read), and the test runs of a version over those samples.

Fields, expected values and results are JSON kept as text and never queried (database portability D5). A version is
only ever inserted: saving fields writes version n+1 in the transaction that moves the type's `latest_version`, so a
workflow pinned to version n keeps reading what it was published with."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any, Literal, NotRequired, TypedDict

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from ops_contracts.field_values import DEFAULT_DATE_ORDER
from ops_documents.store.columns import JSON_TEXT
from ops_documents.store.metadata import RECOVER_PENDING, ROLE, SYSTEM_ROLE, metadata
from ops_service_kit.http import Json, JsonList, JsonValue, Out
from ops_service_kit.listing import ListParams
from ops_store import isolation
from ops_store.dialect import locked
from ops_store.listing import LISTED, ListPage, list_page
from ops_store.rows import one, rows
from ops_store.schema import TENANT_SCOPED, team_owned
from ops_store.store import Store
from ops_store.team_scope import any_team, team_visible

TestStatus = Literal["queued", "running", "done", "failed"]

document_types = sa.Table(
    "document_types",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("team", sa.String(64), nullable=False),
    # The list sorts on it; uq_document_types_name (tenant, team, name) is its index.
    sa.Column("name", sa.String(200), nullable=False, info=LISTED),
    sa.Column("description", sa.String(1000)),
    # The list sorts on it (sortBy=latestVersion); ix_document_types_latest_version is its index.
    sa.Column("latest_version", sa.Integer, nullable=False, info=LISTED),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    # A name names one type in its team, so a picker never shows two "Levy notice".
    sa.UniqueConstraint("tenant_id", "team", "name", name="uq_document_types_name"),
    sa.Index("ix_document_types_latest_version", "tenant_id", "team", "latest_version"),
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
    # Layout templates, JSON; null on versions saved before, read as none.
    sa.Column("templates", sa.Text),
    # Checks across fields, JSON; null on versions saved before, read as none.
    sa.Column("checks", sa.Text),
    # Whether reads may show the model the page image; null on versions saved before, read as off.
    sa.Column("page_images", sa.Boolean),
    # How many checked reads of one layout offer a template; null on versions saved before, read as the default.
    sa.Column("offer_at", sa.Integer),
    sa.Column("note", sa.String(500)),
    sa.Column("created_by", sa.String(320), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    # The type's team, copied when the version is written, so the policy holds it without reading the type.
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


# A type's examples: the corrections people made on its reads, as the field, the line its value was printed on
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
# How many examples of one field a team's type keeps: a new one drops the oldest past this. Reads are given the
# newest few, so the rest only let a person remove a wrong one without a gap; nothing grows without bound.
EXAMPLES_KEPT_PER_FIELD = 10


class NameTakenError(Exception):
    """Another type in the team has this name, or the id is taken."""


class TypeRow(Out):
    """A team's document type."""

    tenant_id: str
    id: str
    team: str
    name: str
    description: str | None
    latest_version: int
    created_by: str
    created_at: datetime


class VersionRow(Out):
    """One version of a type, its JSON read. A version saved before an option was a column holds null in it."""

    tenant_id: str
    type_id: str
    version: int
    fields: Annotated[list[Json], JSON_TEXT]
    many: bool
    review_below: float | None
    date_order: str | None
    templates: Annotated[list[Json] | None, JSON_TEXT]
    checks: Annotated[list[Json] | None, JSON_TEXT]
    page_images: bool | None
    offer_at: int | None
    note: str | None
    created_by: str
    created_at: datetime
    team: str


class SampleRow(Out):
    """A file of the team's and the values it should read: {key: value}, or a list of them for a type reading
    several records."""

    id: str
    type_id: str
    file_id: str
    name: str
    expected: Annotated[Any, JSON_TEXT]
    added_by: str
    added_at: datetime


class ExampleRow(Out):
    """A correction a type's reads are given: the field, the line its value was printed on and the corrected value.
    `record` is SINGLE for a read of one record."""

    id: str
    field: str
    line: str | None
    value: Annotated[Any, JSON_TEXT]
    extraction_id: str
    record: int
    corrected_by: str
    created_at: datetime


class TestRow(Out):
    """One test run of a version over the type's samples, its result read once it is done."""

    __test__ = False  # not a pytest test class, though its name starts with Test

    tenant_id: str
    id: str
    type_id: str
    version: int
    team: str
    status: TestStatus
    samples: int
    result: Annotated[Json | None, JSON_TEXT]
    error: str | None
    asked_by: str
    asked_at: datetime
    finished_at: datetime | None


class NewType(TypedDict):
    """A new type's row, before its version 1."""

    tenant_id: str
    id: str
    team: str
    name: str
    description: JsonValue
    created_by: str
    created_at: datetime


class VersionOptions(TypedDict):
    """A version's fields and options, checked as an extraction request checks them."""

    fields: JsonList
    many: bool
    review_below: JsonValue
    date_order: str
    templates: JsonList
    checks: JsonList
    page_images: bool
    offer_at: int
    note: JsonValue


class NewVersion(VersionOptions):
    created_by: str
    created_at: datetime


class _VersionValues(TypedDict):
    """A version's row as it is inserted, its JSON as text."""

    tenant_id: str
    type_id: str
    team: object
    version: int
    fields: str
    many: bool
    review_below: JsonValue
    date_order: str
    templates: str
    checks: str
    page_images: bool
    offer_at: int | None
    note: JsonValue
    created_by: str
    created_at: datetime


class FieldCompared(TypedDict):
    """One sample's expected value of a field against the value read."""

    expected: JsonValue
    got: JsonValue
    match: bool


class SampleCompared(TypedDict):
    """One sample in a test result, keys in the order stored. `path` and `templateId` say how the sample was read,
    when a layout template read it; `fields` is empty when the read did not finish."""

    sampleId: str
    name: str
    extractionId: JsonValue
    status: JsonValue
    path: NotRequired[JsonValue]
    templateId: NotRequired[JsonValue]
    fields: NotRequired[dict[str, list[FieldCompared]]]


class FieldScore(TypedDict):
    matches: int
    misses: int
    accuracy: float | None


class TestResult(TypedDict):
    """A finished test run's result: each sample compared, then each field's score over them, then the overall one."""

    samples: list[SampleCompared]
    fields: dict[str, FieldScore]
    accuracy: float | None


class TestChange(TypedDict, total=False):
    """What a test run's progress changes on its row."""

    status: TestStatus
    result: TestResult
    error: str
    finished_at: datetime


def _named(table: sa.Table, model: type[Out]) -> tuple[sa.Column[Any], ...]:
    """The table's columns the row model names, in the model's order."""
    return tuple(table.c[name] for name in model.model_fields if name in table.c)


def _type_team(type_id: str) -> Any:
    """The type's team; another team's type is not visible, so a row naming it has no team and is refused."""
    t = document_types
    return sa.select(t.c.team).where(t.c.id == type_id, team_visible(t)).scalar_subquery()


SAMPLE = _named(document_type_samples, SampleRow)
EXAMPLE = _named(document_type_examples, ExampleRow)


class DocumentTypesStore(Store):
    role = ROLE
    system_role = SYSTEM_ROLE

    async def create(self, values: NewType, version: NewVersion) -> None:
        """The type and its version 1, in one transaction."""
        async with self.tx() as c:
            try:
                async with self.attempt(c):
                    await c.execute(sa.insert(document_types).values(**values, latest_version=1))
                    row = self._version(values["tenant_id"], values["id"], values["team"], version, 1)
                    await c.execute(sa.insert(document_type_versions).values(**row))
            except IntegrityError as e:
                raise NameTakenError(str(values["name"])) from e

    async def add_version(self, type_id: str, version: NewVersion) -> int:
        """Inserts version latest+1 and moves the type to it; a concurrent save fails on the version key."""
        tenant = isolation.tenant()
        async with self.tx() as c:
            head = sa.select(document_types.c.latest_version).where(
                document_types.c.tenant_id == tenant, document_types.c.id == type_id, team_visible(document_types)
            )
            latest = (await c.execute(locked(head, document_types))).scalar_one()
            n = int(latest) + 1
            row = self._version(tenant, type_id, _type_team(type_id), version, n)
            await c.execute(sa.insert(document_type_versions).values(**row))
            await c.execute(
                sa.update(document_types)
                .where(document_types.c.tenant_id == tenant, document_types.c.id == type_id)
                .values(latest_version=n)
            )
        return n

    @staticmethod
    def _version(tenant_id: str, type_id: str, team: object, version: NewVersion, n: int) -> _VersionValues:
        return {
            "tenant_id": tenant_id,
            "type_id": type_id,
            "team": team,
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

    async def get(self, type_id: str) -> TypeRow | None:
        t = document_types.c
        q = sa.select(document_types).where(
            t.tenant_id == isolation.tenant(), t.id == type_id, team_visible(document_types)
        )
        async with self.tx() as c:
            return await one(c, q, TypeRow)

    async def every(self, team: str) -> list[TypeRow]:
        """Every type of the team, by name: what classification chooses among."""
        t = document_types.c
        q = (
            sa.select(document_types)
            .where(t.tenant_id == isolation.tenant(), t.team == team, team_visible(document_types))
            .order_by(t.name, t.id)
        )
        async with self.tx() as c:
            return await rows(c, q, TypeRow)

    async def list(self, team: str, params: ListParams) -> tuple[list[TypeRow], ListPage]:
        """One page of the team's types on the shared list contract, by name, searched on the name. sortBy=name turns
        it, sortBy=latestVersion orders by the newest version with equal versions by name; uq_document_types_name and
        ix_document_types_latest_version serve the orders."""
        t = document_types.c
        query = sa.select(document_types).where(
            t.tenant_id == isolation.tenant(), t.team == team, team_visible(document_types)
        )
        async with self.tx() as c:
            page = await list_page(
                c,
                query,
                params,
                search=[t.name],
                sortable={"name": t.name, "latestVersion": t.latest_version},
                default_sort=t.name.asc(),
            )
        return [TypeRow.model_validate(r) for r in page["data"]], page

    async def version(self, type_id: str, n: int) -> VersionRow | None:
        v = document_type_versions.c
        q = sa.select(document_type_versions).where(
            v.tenant_id == isolation.tenant(),
            v.type_id == type_id,
            v.version == n,
            team_visible(document_type_versions),
        )
        async with self.tx() as c:
            return await one(c, q, VersionRow)

    async def versions(self, type_id: str) -> list[VersionRow]:
        v = document_type_versions.c
        q = (
            sa.select(document_type_versions)
            .where(v.tenant_id == isolation.tenant(), v.type_id == type_id, team_visible(document_type_versions))
            .order_by(v.version.desc())
        )
        async with self.tx() as c:
            return await rows(c, q, VersionRow)

    async def add_sample(self, tenant_id: str, sample: SampleRow) -> None:
        values = sample.model_dump()
        async with self.tx() as c:
            await c.execute(
                sa.insert(document_type_samples).values(
                    **{
                        "tenant_id": tenant_id,
                        **values,
                        "expected": json.dumps(values["expected"]),
                        "team": _type_team(sample.type_id),
                    }
                )
            )

    async def samples(self, type_id: str) -> list[SampleRow]:
        sm = document_type_samples.c
        q = (
            sa.select(*SAMPLE)
            .where(sm.tenant_id == isolation.tenant(), sm.type_id == type_id, team_visible(document_type_samples))
            .order_by(sm.added_at, sm.id)
        )
        async with self.tx() as c:
            return await rows(c, q, SampleRow)

    async def remove_sample(self, type_id: str, sample_id: str) -> SampleRow | None:
        sm = document_type_samples.c
        q = (
            sa.delete(document_type_samples)
            .where(sm.tenant_id == isolation.tenant(), sm.type_id == type_id, sm.id == sample_id)
            .returning(*SAMPLE)
        )
        async with self.tx() as c:
            return await one(c, q, SampleRow)

    async def examples(self, team: str, type_id: str) -> list[ExampleRow]:
        """The type's examples in the team, newest first."""
        tenant = isolation.tenant()
        e = document_type_examples.c
        q = (
            sa.select(*EXAMPLE)
            .where(e.tenant_id == tenant, e.team == team, e.type_id == type_id, team_visible(document_type_examples))
            .order_by(e.created_at.desc(), e.id.desc())
        )
        async with self.tx() as c:
            return await rows(c, q, ExampleRow)

    async def recent_examples(
        self, team: str, type_id: str, fields: list[str], *, per_field: int, total: int
    ) -> list[ExampleRow]:
        """What a read of the type is given: for the fields it asks, the newest `per_field` examples of each, newest
        first, at most `total` in all."""
        tenant = isolation.tenant()
        e = document_type_examples.c
        q = (
            sa.select(*EXAMPLE)
            .where(
                e.tenant_id == tenant,
                e.team == team,
                e.type_id == type_id,
                e.field.in_(fields),
                team_visible(document_type_examples),
            )
            .order_by(e.created_at.desc(), e.id.desc())
        )
        async with self.tx() as c:
            newest = await rows(c, q, ExampleRow)
        kept: list[ExampleRow] = []
        counts: dict[str, int] = {}
        for example in newest:
            if counts.get(example.field, 0) >= per_field:
                continue
            counts[example.field] = counts.get(example.field, 0) + 1
            kept.append(example)
            if len(kept) >= total:
                break
        return kept

    async def remove_example(self, team: str, type_id: str, example_id: str) -> bool:
        tenant = isolation.tenant()
        e = document_type_examples.c
        async with self.tx() as c:
            gone = await c.execute(
                sa.delete(document_type_examples).where(
                    e.tenant_id == tenant, e.team == team, e.type_id == type_id, e.id == example_id
                )
            )
        return bool(gone.rowcount)

    async def delete(self, team: str, type_id: str) -> bool:
        """Deletes the team's type with its versions, samples, examples and tests; reads already made keep their own
        fields. False when the team holds no such type."""
        tenant = isolation.tenant()
        t = document_types.c
        async with self.tx() as c:
            gone = await c.execute(
                sa.delete(document_types).where(
                    t.tenant_id == tenant, t.team == team, t.id == type_id, team_visible(document_types)
                )
            )
            if not gone.rowcount:
                return False
            for table in (document_type_versions, document_type_samples, document_type_examples, document_type_tests):
                await c.execute(sa.delete(table).where(table.c.tenant_id == tenant, table.c.type_id == type_id))
        return True

    async def insert_test(self, test: TestRow) -> None:
        values = test.model_dump()
        values["result"] = json.dumps(test.result) if test.result is not None else None
        async with self.tx() as c:
            await c.execute(sa.insert(document_type_tests).values(**values))

    async def set_test(self, test_id: str, values: TestChange) -> None:
        tenant = isolation.tenant()
        row = {**values}
        if "result" in row and row["result"] is not None:
            row["result"] = json.dumps(row["result"])
        async with self.tx() as c:
            await c.execute(
                sa.update(document_type_tests)
                .where(document_type_tests.c.tenant_id == tenant, document_type_tests.c.id == test_id)
                .values(**row)
            )

    async def test(self, test_id: str) -> TestRow | None:
        k = document_type_tests.c
        q = sa.select(document_type_tests).where(
            k.tenant_id == isolation.tenant(), k.id == test_id, team_visible(document_type_tests)
        )
        async with self.tx() as c:
            return await one(c, q, TestRow)

    async def pending_tests(self) -> list[TestRow]:
        """Every queued or running test run, across tenants: what a restart picks up again, each then run as its own
        tenant and team."""
        t = document_type_tests
        q = (
            sa.select(t)
            .where(t.c.status.in_(("queued", "running")), any_team(t, RECOVER_PENDING))
            .order_by(t.c.asked_at)
        )
        async with self.system_tx(RECOVER_PENDING) as c:
            return await rows(c, q, TestRow)

    async def purge_samples(self, team: str, file_id: str) -> int:
        """Removes the samples naming a deleted file on the team's document types; the number removed."""
        tenant = isolation.tenant()
        teams_types = sa.select(document_types.c.id).where(
            document_types.c.tenant_id == tenant, document_types.c.team == team, team_visible(document_types)
        )
        async with self.tx() as c:
            gone = await c.execute(
                sa.delete(document_type_samples).where(
                    document_type_samples.c.tenant_id == tenant,
                    document_type_samples.c.file_id == file_id,
                    document_type_samples.c.type_id.in_(teams_types),
                )
            )
        return int(gone.rowcount or 0)
