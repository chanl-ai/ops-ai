# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""What a source answers, by role, as a service that reads it sees each answer.

The roles are the knowledge-source contract a plugin declares (`ops_plugin_sdk.manifest.KnowledgeSource`); this
module names them for every reader and turns each answer into the shape the loop works on:

- Find places: the `scopes` tool (list_scopes) answers `{scopes: [{id, title, kind, parent, detail}], next_cursor}`.
- Changes since a place: the `list` tool (list_items), or `changes` (list_changes) once a run has its cursor,
  answers `{items: [{id, updated_at, marker?, ...}], next_cursor, watermark?, cursor?}`, read page by page.
- Fetch a version: the `get` tool (get_item), sent `tag` when it takes one, answers the item with `content`, or
  `{unchanged: true}` when the tag still matches.
- Access list: `allowed` on a fetched item, the ids that may see it at the source; absent when not known.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

from pydantic import BaseModel, ConfigDict

from ops_service_kit.http import Json, JsonValue
from ops_service_kit.narrow import json_list, json_object

# A sign-in the system refused: the source waits for a reconnect instead of retrying every schedule.
RECONNECT = {"AUTH_EXPIRED", "CONNECTION_REVOKED", "SIGN_IN_NOT_FOUND", "CONNECTION_NOT_LINKED", "SECRET_MISSING"}
# Items fetched at once from the system when the source names no number of its own.
AT_ONCE = 4


@dataclass(frozen=True)
class Answer:
    """One tool call's outcome: the output when ok, else the error code and message."""

    ok: bool
    output: JsonValue = None
    code: str = ""
    message: str = ""


@dataclass(frozen=True)
class SourceTools:
    """The tools one source is read with, by role, and how its system wants to be read."""

    list: str | None
    get: str | None
    changes: str | None = None
    # Every listing names every item (a site's sitemap), so each run is a full listing.
    lists_whole: bool = False
    fetch_at_once: int = AT_ONCE
    # The get tool takes the held version tag and answers `unchanged` when it still matches.
    get_takes_tag: bool = False

    @classmethod
    def of(cls, row: Mapping[str, object]) -> SourceTools:
        """The tools named by a declared source, or by a reading service's stored copy of one (the same keys). A tool
        the row names as null stays None, so the loop refuses to call it rather than call a tool named "None"."""

        def tool(key: str) -> str | None:
            named = row.get(key)
            return str(named) if named else None

        at_once = row.get("fetchAtOnce")
        return cls(
            list=tool("listTool"),
            get=tool("getTool"),
            changes=tool("changesTool"),
            lists_whole=bool(row.get("listsWhole")),
            # A string or float an older writer stored still reads.
            fetch_at_once=int(at_once) if isinstance(at_once, int | float | str) and at_once else AT_ONCE,
            get_takes_tag=bool(row.get("getTakesTag")),
        )


class Declared(BaseModel):
    """A source as tools-service declares it for a team (`GET /v1/knowledge-sources`): the tools that list, fetch,
    change-watch, pick and preview it, how its connection signs in, and the inputs its settings are checked against."""

    model_config = ConfigDict(extra="ignore")

    plugin: str
    source: str
    title: str
    needsConnection: bool = True  # noqa: N815 - the wire names follow
    connectionId: str | None = None  # noqa: N815
    connectionStatus: str | None = None  # noqa: N815
    signIn: str | None = None  # noqa: N815
    listTool: str | None = None  # noqa: N815
    getTool: str | None = None  # noqa: N815
    changesTool: str | None = None  # noqa: N815
    scopesTool: str | None = None  # noqa: N815
    previewTool: str | None = None  # noqa: N815
    listsWhole: bool = False  # noqa: N815
    fetchAtOnce: int | None = None  # noqa: N815
    site: bool = False
    files: bool = False
    getTakesTag: bool = False  # noqa: N815
    schedule: dict[str, JsonValue] | None = None
    inputs: dict[str, dict[str, JsonValue]] = {}

    @property
    def tools(self) -> SourceTools:
        return SourceTools.of(self.model_dump())


class SourceError(TypedDict, total=False):
    """One page or item a read could not settle."""

    itemTitle: str | None
    phase: str
    errorClass: str | None
    message: str | None


@dataclass(frozen=True)
class FoundPlace:
    """One place a person can pick to read from: a site, a library, a folder, a space."""

    id: str
    title: str
    kind: str
    parent: str | None
    detail: str | None


def places_of(output: JsonValue) -> tuple[list[FoundPlace], str | None]:
    """A find-places answer: the places on this page and the cursor of the next, if any."""
    out = json_object(output)
    rows = out.get("scopes")
    places = [
        FoundPlace(
            id=str(r["id"]),
            title=str(r.get("title") or r["id"]),
            kind=str(r.get("kind") or ""),
            parent=str(r["parent"]) if r.get("parent") else None,
            detail=str(r["detail"]) if r.get("detail") else None,
        )
        for r in (rows if isinstance(rows, list) else [])
        if isinstance(r, dict) and r.get("id")
    ]
    following = out.get("next_cursor")
    return places, str(following) if following else None


def listing_of(output: JsonValue) -> list[Json] | None:
    """A changes page's items when the answer is a listing (each item has an id and updated_at), else None."""
    if not isinstance(output, dict):
        return None
    items = output.get("items")
    if not isinstance(items, list):
        return None
    if not all(isinstance(r, dict) and {"id", "updated_at"} <= set(r) for r in items):
        return None
    return [json_object(r) for r in items]


def access_list(item: Json) -> list[str] | None:
    """Who may see a fetched item at its source: None when the source did not say, [] when it listed nobody."""
    if not isinstance(item.get("allowed"), list):
        return None
    return [str(a) for a in json_list(item["allowed"])]
