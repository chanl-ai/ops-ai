"""Human Task types and their versions (c-288), per tenant, on the typed-record store (store/typed_records.py).

The general types are seeded from seed/task_types.json. A workflow in one team may use another team's type. A task
keeps the screen it was opened with (`published`, read by id and version, is what a review step and the task API pin).
"""

from __future__ import annotations

from typing import Any, ClassVar

import sqlalchemy as sa

from ops_store.schema import TEAM_OWNED, TENANT_SCOPED

from .base import metadata
from .typed_records import SEED, TEAM, RecordNotFound, VersionedRecords, head_columns, version_columns

__all__ = ["SEED", "TEAM", "TaskTypeNotFound", "TaskTypeStore", "record_of", "task_type_versions", "task_types"]

task_types = sa.Table("task_types", metadata, *head_columns(), info={**TENANT_SCOPED, **TEAM_OWNED})
task_type_versions = sa.Table(
    "task_type_versions",
    metadata,
    *version_columns(),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)

_RECORD_KEYS = ("name", "description", "params", "regions", "actions", "defaults")


def record_of(content: dict[str, Any]) -> dict[str, Any]:
    return {k: content[k] for k in _RECORD_KEYS if k in content}


class TaskTypeNotFound(RecordNotFound):
    code = "task_type_not_found"
    title: ClassVar[str] = "Task type"


class TaskTypeStore(VersionedRecords):
    head = task_types
    versions = task_type_versions
    record_keys = _RECORD_KEYS
    noun = "task type"
    taken_code = "task_type_taken"
    not_found = TaskTypeNotFound
