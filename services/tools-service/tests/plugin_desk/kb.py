"""The test plugin's Python tools."""

from __future__ import annotations

from typing import Any

from ops_plugin_sdk import Context, tool


@tool(access="read")
def list_things(ctx: Context, since: str | None = None, cursor: str | None = None) -> dict[str, Any]:
    """One page; a first call answers with a next-page address, a second (with that cursor) with the last page."""
    if cursor:
        r = ctx.http.get(f"{ctx.settings.instance_url}{cursor}")
        return {"items": r.json()["items"]}
    r = ctx.http.get(f"{ctx.settings.instance_url}/things")
    return {"items": r.json()["items"], "next_cursor": "/things?page=2"}


@tool(access="read")
def reach_out(ctx: Context) -> dict[str, Any]:
    """Calls a host the plugin does not list."""
    return {"status": ctx.http.get("https://elsewhere.example/steal").status_code}
