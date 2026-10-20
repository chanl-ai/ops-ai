"""What the routes of every typed-record kind share (task types, c-288; case types, c-291): the views of a type and its
versions, the owning team of a new one, and the `can()` check on an existing one. A kind's router adds only how its
record is checked."""

from __future__ import annotations

from typing import Any

from ops_access import can
from ops_service_kit.errors import Unprocessable

from ..store.tenancy import current_team
from ..store.typed_records import SEED, VersionedRecords
from .auth import Principal, caller_of
from .schemas import Out


class RecordTypeView(Out):
    id: str
    name: str
    description: str
    origin: str
    team_id: str | None
    version: int
    published_version: int | None
    copied_from: dict[str, Any] | None
    updated_at: str
    updated_by: str


class RecordVersionView(Out):
    version: int
    record: dict[str, Any]
    saved_at: str
    saved_by: str
    published_at: str | None


def view(row: dict[str, Any]) -> dict[str, Any]:
    return RecordTypeView(**{k: row[k] for k in RecordTypeView.model_fields}).model_dump(mode="json", by_alias=True)


def detail(row: dict[str, Any]) -> dict[str, Any]:
    versions = [RecordVersionView(**{k: v[k] for k in RecordVersionView.model_fields}) for v in row["versions"]]
    return {**view(row), "versions": [v.model_dump(mode="json", by_alias=True) for v in versions]}


def team_of(me: Principal, noun: str) -> str:
    team = current_team() or me.team_id
    if not team:
        raise Unprocessable(
            f"Choose a team with the X-Team-Id header; a {noun} belongs to one team.", code="team_required"
        )
    return team


def by_of(me: Principal) -> str:
    return me.email or me.sub


async def owned(store: VersionedRecords, me: Principal, type_id: str, action: str) -> dict[str, Any]:
    """The type, when the caller may `action` it. A seeded type is a system record: can() lets those who manage
    workflows (admins) change it, as any system record (register E05), and a team copies it to make its own."""
    row = await store.get(type_id)
    protection = "system" if row["origin"] == SEED else None
    can(caller_of(me), "workflows", action, team=row["team_id"], what=f"this {store.noun}", protection=protection)
    return row
