"""Case types and their versions (c-291), per tenant, on the typed-record store (store/typed_records.py): the fields a
case shows and their order. The general types are seeded from seed/case_types.json. A case pins the published version
it was opened with (`cases.type_id`, `type_version`), so editing a type never changes a case already open."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED, team_owned_via

from .base import metadata
from .typed_records import RecordNotFound, VersionedRecords, head_columns, version_columns

case_types = sa.Table("case_types", metadata, *head_columns(), info={**TENANT_SCOPED, **TEAM_OWNED})
case_type_versions = sa.Table(
    "case_type_versions",
    metadata,
    *version_columns(),
    info={**TENANT_SCOPED, **team_owned_via("case_types", "type_id")},
)


class CaseTypeNotFound(RecordNotFound):
    code = "case_type_not_found"
    title: ClassVar[str] = "Case type"


class CaseTypeStore(VersionedRecords):
    head = case_types
    versions = case_type_versions
    record_keys = ("name", "description", "fields")
    noun = "case type"
    taken_code = "case_type_taken"
    not_found = CaseTypeNotFound
