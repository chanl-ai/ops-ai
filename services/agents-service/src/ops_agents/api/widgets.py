"""Widget templates (c-082, `.codeloop/wiki/concepts/chat-widgets.md`): checking what a builder saves, the views the
console reads, and the publish an approved review runs. The seeded library (seed/widgets.json, in the catalogue) is
served beside the registry's widgets as published, platform-wide templates; the registry's are scoped to the team
that made them.
"""

from __future__ import annotations

import re
from typing import Any, cast

from ops_agent_kernel import layout
from ops_agents.activities.catalog import WidgetPinRule
from ops_agents.store.widgets import WidgetRegistry
from ops_service_kit.errors import Unprocessable

from .agent_registry import registry
from .deps import Runtime

MAX_WIDGET_ID = 64


def widgets(rt: Runtime) -> WidgetRegistry:
    return WidgetRegistry(rt.db)


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


def _status(row: dict[str, Any], newest: dict[str, Any], pending: bool) -> str:
    if row["retired_reason"]:
        return "deprecated"
    if pending:
        return "in_review"
    return "published" if newest["published_at"] is not None else "draft"


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
    newest = await reg.version(widget_id, int(row["version"]))
    assert newest is not None
    pending = any(r["status"] == "pending" for r in await _requests(rt, widget_id))
    return _out(
        widget_id,
        int(row["version"]),
        newest["content"],
        status=_status(row, newest, pending),
        teamId=row["team_id"],
        updatedBy=row["updated_by"],
        updatedAt=row["updated_at"],
    )


async def _requests(rt: Runtime, widget_id: str) -> list[dict[str, Any]]:
    return await registry(rt).requests("widget", widget_id)


async def seeded_widgets(rt: Runtime) -> list[dict[str, Any]]:
    """The seeded library's latest versions, by name: a fixed handful from seed/widgets.json, platform-wide."""
    seeded = {w.widget_id: w for w in sorted(rt.catalog.widgets, key=lambda w: w.version)}
    out = [
        w.model_dump(by_alias=True) | {"status": "published", "requiresTools": layout.required_tools(w.tree)}
        for w in seeded.values()
    ]
    return sorted(out, key=lambda w: str(w["name"]))


async def listed(rt: Runtime, teams: list[str] | None) -> list[dict[str, Any]]:
    """The seeded library's latest versions, then the registry's widgets in the caller's teams (all teams for a caller
    with no team list, the dev caller), newest version each, by name."""
    out = await seeded_widgets(rt)
    for row in await widgets(rt).rows():
        if teams is None or row["team_id"] in teams:
            out.append(await view(rt, row["id"]))
    return sorted(out, key=lambda w: str(w["name"]))


async def published(rt: Runtime, widget_id: str, version: int | None) -> WidgetPinRule | None:
    """A published version an agent may pin: the registry's (not retired), else the seeded library's; the latest
    published when `version` is None."""
    reg = widgets(rt)
    row = await reg.find(widget_id)
    if row is not None:
        if row["retired_reason"] or row["published_version"] is None:
            return None
        n = int(row["published_version"]) if version is None else version
        v = await reg.version(widget_id, n)
        if v is None or v["published_at"] is None:
            return None
        return WidgetPinRule.model_validate({"widgetId": widget_id, "version": n, **v["content"]})
    return rt.catalog.widget(widget_id, version)


async def publish(rt: Runtime, req: dict[str, Any], by: str) -> None:
    """An approved review's publish: the requested version becomes the one agents may pin."""
    await widgets(rt).publish(req["subject_id"], int(req["version"]), by=by, review_id=req["id"])
