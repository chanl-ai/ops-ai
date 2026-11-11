"""Case and task type copies for `/v1/templates`: made, read and saved through each type's own routes, so a copy can
never be something a person's create or save would refuse, and merged field by field like every other kind.

A copy takes an id of its own in the team (`ct_…`, `tt_…`): types are keyed by tenant, team and id, so a template's id
written as the type's would collide with a second pack's type of the same id, and the template id lives on the copy
link only. A copy starts as draft version 1, as a type a person creates does, and goes live through the type's own
publish. An update merges the type's top-level fields, and each case field or task action by its key, so two sides
that changed different fields never conflict."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

from ops_service_kit.errors import NotFound
from ops_service_kit.ids import new_id

from ..auth import Principal
from ..case_type_seeds import case_type_store
from ..deps import Runtime
from ..task_type_seeds import task_type_store
from . import case_types as case_routes
from . import task_types as task_routes

TypeKind = Literal["case_type", "task_type"]
TYPE_KINDS: tuple[TypeKind, ...] = ("case_type", "task_type")
# The list merged item by item, and the key that names an item.
ITEMS: dict[str, tuple[str, str]] = {"case_type": ("fields", "key"), "task_type": ("actions", "id")}
# The other fields an update compares; the name is the team's (a binding).
TOP: dict[str, tuple[str, ...]] = {
    "case_type": ("description", "deadline"),
    "task_type": ("description", "params", "regions", "defaults"),
}
PREFIX = {"case_type": "ct", "task_type": "tt"}
LABELS = {"description": "description", "deadline": "deadline", "params": "inputs", "regions": "layout",
          "defaults": "defaults"}  # fmt: skip


async def _store(rt: Runtime, kind: str) -> Any:
    return await (case_type_store(rt) if kind == "case_type" else task_type_store(rt))


def body_of(kind: str, t: dict[str, Any]) -> dict[str, Any]:
    """The template's body as the type's record holds it, without its id."""
    b = cast(dict[str, Any], t.get("body") or {})
    keys = ("name", *TOP[kind], ITEMS[kind][0])
    out = {k: b[k] for k in keys if k in b}
    out.setdefault("name", t["title"])
    out.setdefault(ITEMS[kind][0], [])
    # Shaped as the type's save route stores a record, so a template body and a saved record of the same content
    # compare equal (a field's `required: false`, an empty description).
    model = case_routes.Definition if kind == "case_type" else task_routes.Definition
    return model.model_validate(out).model_dump(mode="json", exclude_none=True)


async def make(rt: Runtime, me: Principal, kind: str, t: dict[str, Any], name: str) -> str:
    """The type's own create route, as a person's create runs it: its role check, its field checks, draft version 1."""
    type_id = new_id(PREFIX[kind])
    body = {k: v for k, v in body_of(kind, t).items() if v is not None} | {"id": type_id, "name": name}
    if kind == "case_type":
        await case_routes.create_case_type(rt, me, case_routes.TypeIn.model_validate(body))
    else:
        await task_routes.create_task_type(rt, me, task_routes.TypeIn.model_validate(body))
    return type_id


async def newest(rt: Runtime, kind: str, type_id: str) -> tuple[dict[str, Any], bool]:
    """The type's newest record and whether that version is an unpublished draft."""
    v = (await (await _store(rt, kind)).get(type_id))["versions"][0]
    return cast(dict[str, Any], v["record"]), v.get("published_at") is None


async def name(rt: Runtime, kind: str, type_id: str) -> str | None:
    try:
        return str((await (await _store(rt, kind)).get(type_id))["name"])
    except NotFound:
        return None


async def digest(rt: Runtime, kind: str, type_id: str) -> str | None:
    """sha256 of the newest record, which a save moves."""
    try:
        record, _ = await newest(rt, kind, type_id)
    except NotFound:
        return None
    return hashlib.sha256(json.dumps(record, sort_keys=True, default=str).encode()).hexdigest()


async def names_in_use(rt: Runtime, kind: str, team: str) -> set[str]:
    return {str(r["name"]).casefold() for r in await (await _store(rt, kind)).rows() if r["team_id"] == team}


async def save(rt: Runtime, me: Principal, kind: str, type_id: str, record: dict[str, Any]) -> int:
    """The type's own save route: a published version opens the next one, a draft is saved over."""
    if kind == "case_type":
        await case_routes.save_case_type(rt, me, type_id, case_routes.Definition.model_validate(record))
    else:
        await task_routes.save_task_type(rt, me, type_id, task_routes.Definition.model_validate(record))
    return int((await (await _store(rt, kind)).get(type_id))["version"])


def flat(kind: str, record: dict[str, Any] | None) -> dict[str, Any] | None:
    """A record as the merge reads it: each item of the merged list under `<field|action>:<key>`."""
    if record is None:
        return None
    items, key = ITEMS[kind]
    out = {k: record.get(k) for k in TOP[kind]}
    for item in cast(list[dict[str, Any]], record.get(items) or []):
        out[f"{items[:-1]}:{item.get(key)}"] = item
    return out


def order(kind: str, *records: dict[str, Any] | None) -> list[str]:
    """The merge's field list: the top-level fields, then items in the team's order, then ones only the template or
    the base names."""
    items, key = ITEMS[kind]
    keys = list(TOP[kind])
    for r in records:
        for item in cast(list[dict[str, Any]], (r or {}).get(items) or []):
            if (k := f"{items[:-1]}:{item.get(key)}") not in keys:
                keys.append(k)
    return keys


def unflat(kind: str, merged: dict[str, Any], keys: list[str], name: str) -> dict[str, Any]:
    items, _ = ITEMS[kind]
    out = {k: merged.get(k) for k in TOP[kind] if merged.get(k) is not None}
    out[items] = [merged[k] for k in keys if k.startswith(f"{items[:-1]}:") and merged.get(k) is not None]
    return {"name": name, **out}


def label(field: str, yours: Any, template: Any) -> str:
    if field in LABELS:
        return LABELS[field]
    named = cast(dict[str, Any], yours or template or {})
    noun, _, key = field.partition(":")
    return f"{noun} {named.get('label') or named.get('name') or key}"


__all__ = ["TYPE_KINDS", "TypeKind", "body_of", "digest", "flat", "label", "make", "name", "names_in_use", "newest",
           "order", "save", "unflat"]  # fmt: skip
