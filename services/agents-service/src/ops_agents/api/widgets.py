"""Widget templates (`docs/architecture/chat-widgets.md`): checking what a builder saves, the views the
console reads, and the publish an approved review runs. The seeded library (seed/widgets.json, in the catalogue) is
served beside the registry's widgets as published, platform-wide templates; the registry's are scoped to the team
that made them.
"""

from __future__ import annotations

import re
from typing import Any, cast

from ops_agent_kernel import layout
from ops_agents.activities.catalog import WidgetPinRule
from ops_agents.store.widget_picker import WidgetPicker
from ops_agents.store.widgets import ListedWidget, WidgetRegistry
from ops_service_kit.errors import Unprocessable

from ..store.agent_registry import PublishRequestRow
from .agent_registry import registry
from .deps import Runtime

MAX_WIDGET_ID = 64


def widgets(rt: Runtime) -> WidgetRegistry:
    return WidgetRegistry(rt.db)


def picker(rt: Runtime) -> WidgetPicker:
    return WidgetPicker(rt.db)


def widget_id_of(name: str) -> str:
    return (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "widget")[:MAX_WIDGET_ID].rstrip("-")


def _binds(node: Any) -> list[str]:
    if isinstance(node, dict):
        d = cast(dict[str, Any], node)
        if set(d) == {"$bind"}:
            return [str(d["$bind"])]
        return [p for v in d.values() for p in _binds(v)]
    if isinstance(node, list):
        return [p for v in cast(list[Any], node) for p in _binds(v)]
    return []


def check_content(fields: dict[str, Any]) -> dict[str, Any]:
    """The content to save, or 422 naming what is wrong: a blank name or use-when line, a data schema that is not a
    JSON Schema object, a `$bind` to a field the schema does not define, or a tree that fails the kernel's catalogue
    check when filled with the sample (the same check every chat turn runs)."""
    name, use_when = str(fields.get("name") or "").strip(), str(fields.get("useWhen") or "").strip()
    if not name:
        raise Unprocessable("Name the widget.", code="invalid_widget")
    if not use_when:
        raise Unprocessable("Say when the agent should use it.", code="invalid_widget")
    try:
        schema = layout.check_schema(fields.get("dataSchema"))
        props = set(cast(dict[str, Any], schema.get("properties") or {}))
        for pointer in _binds(fields.get("tree")):
            top = pointer.lstrip("/").split("/")[0]
            if top not in props:
                raise layout.LayoutError(f"The layout binds {pointer}, which the data schema does not define.")
        sample = cast(dict[str, Any], fields.get("sample") or {})
        layout.fill(fields.get("tree"), schema, sample)
    except layout.LayoutError as e:
        raise Unprocessable(str(e), code="invalid_widget") from e
    return {"name": name, "useWhen": use_when, "tree": fields["tree"], "dataSchema": schema, "sample": sample}


def _out(widget_id: str, version: int, content: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "widgetId": widget_id,
        "version": version,
        "name": content["name"],
        "useWhen": content["useWhen"],
        "tree": content["tree"],
        "dataSchema": content["dataSchema"],
        "sample": content.get("sample"),
        "requiresTools": layout.required_tools(content["tree"]),
        **extra,
    }


async def view(rt: Runtime, widget_id: str) -> dict[str, Any]:
    reg = widgets(rt)
    row = await reg.row(widget_id)
    newest = await reg.version(widget_id, row.version)
    assert newest is not None
    pending = any(r.status == "pending" for r in await _requests(rt, widget_id))
    return listed_view(
        ListedWidget.model_validate(
            {**row.model_dump(), "content": newest.content, "published_at": newest.published_at, "pending": pending}
        )
    )


def listed_view(w: ListedWidget) -> dict[str, Any]:
    """A widget's reply: its newest version's content, and its status (retired, in review, published or draft)."""
    status = (
        "deprecated"
        if w.retired_reason
        else "in_review"
        if w.pending
        else "draft"
        if w.published_at is None
        else "published"
    )
    return _out(
        w.id, w.version, w.content, status=status, teamId=w.team_id, updatedBy=w.updated_by, updatedAt=w.updated_at
    )


async def _requests(rt: Runtime, widget_id: str) -> list[PublishRequestRow]:
    return await registry(rt).requests("widget", widget_id)


async def seeded_widgets(rt: Runtime) -> list[dict[str, Any]]:
    """The seeded library's latest versions, by name: a fixed handful from seed/widgets.json, platform-wide."""
    seeded = {w.widget_id: w for w in sorted(rt.catalog.widgets, key=lambda w: w.version)}
    out = [
        w.model_dump(by_alias=True) | {"status": "published", "requiresTools": layout.required_tools(w.tree)}
        for w in seeded.values()
    ]
    return sorted(out, key=lambda w: str(w["name"]))


async def listed_one(rt: Runtime, teams: list[str], widget_id: str) -> dict[str, Any] | None:
    """The widget `widget_id` as the caller sees it, reading only that widget: the seeded library's latest version
    first, else the registry's newest version when it is in the caller's teams."""
    seeded = next((w for w in await seeded_widgets(rt) if w["widgetId"] == widget_id), None)
    if seeded is not None:
        return seeded
    row = await widgets(rt).find(widget_id)
    return await view(rt, widget_id) if row is not None and row.team_id in teams else None


async def published(rt: Runtime, widget_id: str, version: int | None) -> WidgetPinRule | None:
    """A published version an agent may pin: the registry's (not retired), else the seeded library's; the latest
    published when `version` is None."""
    reg = widgets(rt)
    row = await reg.find(widget_id)
    if row is not None:
        if row.retired_reason or row.published_version is None:
            return None
        n = row.published_version if version is None else version
        v = await reg.version(widget_id, n)
        if v is None or v.published_at is None:
            return None
        return WidgetPinRule.model_validate({"widgetId": widget_id, "version": n, **v.content})
    return rt.catalog.widget(widget_id, version)


async def publish(rt: Runtime, req: PublishRequestRow, by: str) -> None:
    """An approved review's publish: the requested version becomes the one agents may pin."""
    await widgets(rt).publish(req.subject_id, int(req.version), by=by, review_id=req.id)
