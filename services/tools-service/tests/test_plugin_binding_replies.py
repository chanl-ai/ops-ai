"""The replies a team's plugin binding feeds, pinned with exact values in each state the binding can be in: no row, a
row a first save made (version, tools and config all null), and a row with every column held. A store change that
reads a column wrong, or turns a null into an empty value, changes one of these replies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from ops_plugin_sdk import Plugin
from ops_tools.plugins.host import PluginHost

from .test_plugin_versions import ID, admin, routes
from .test_reply_pins import WRITE, normal

__all__ = ["routes"]

APP = f"plugin:{ID}"
# Rewritten with OPS_WRITE_PINS=1 (test_reply_pins), only where a reply is meant to change.
PINS = Path(__file__).parent / "fixtures" / "plugin_binding_replies.json"


async def _replies(c: httpx.AsyncClient, tenant: str) -> dict[str, Any]:
    h = admin(tenant)
    card = next(a for a in (await c.get("/v1/apps", headers=h)).json()["data"] if a["id"] == APP)
    out: dict[str, Any] = {"card": card}
    for name, url in (
        ("page", f"/v1/apps/{APP}"),
        ("update", f"/v1/apps/{APP}/update"),
        ("accounts", f"/v1/apps/{APP}/accounts"),
    ):
        r = await c.get(url, headers=h)
        out[name] = {"status": r.status_code, "body": r.json()}
    return normal(out, tenant)


async def test_each_binding_state_answers_as_it_did(
    routes: tuple[httpx.AsyncClient, PluginHost, Plugin], tenant: str
) -> None:
    c, host, _ = routes
    seen: dict[str, Any] = {"none": await _replies(c, tenant)}
    await host.bindings.put(tenant, "team_ops", ID, enabled=True, connection_id=None, settings={}, by="t")
    seen["first_save"] = await _replies(c, tenant)
    on = await c.put(
        f"/v1/apps/{APP}/team",
        json={"enabled": True, "credentials": {"token": "t-1"}, "settings": {"api_version": "2026-11"}},
        headers=admin(tenant),
    )
    assert on.status_code == 200, on.text
    await host.bindings.set_tools(tenant, "team_ops", ID, ["search"])
    await host.bindings.set_config(tenant, "team_ops", ID, {"region": "eu"}, {"region": "default"}, by="t")
    seen["held"] = await _replies(c, tenant)
    if WRITE:
        PINS.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n")
    assert seen == json.loads(PINS.read_text())
