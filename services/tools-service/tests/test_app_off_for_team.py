"""A call to an app the caller's team has off, by failure mode: it is refused with the same code as an app the install
does not load, so a chat cannot tell "ask an admin to turn it on" from "not installed"; and the refusal leaves out the
app and team, so nothing can name what to turn on or for whom."""

from __future__ import annotations

from typing import Any

from ops_identity import dev_service_signer, mint_service_token
from ops_tools.gateway_calls import _before_policy  # pyright: ignore[reportPrivateUsage]
from ops_tools.registry import Resolved

from .test_my_connectors import SITES, _sites_on  # pyright: ignore[reportPrivateUsage]
from .test_plugin_manifest_fields import (  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures
    TokenDesk,
    desk_rig,  # pyright: ignore[reportUnusedImport]
)

SECURITY = "team_security"


def run_in(tenant: str, team: str) -> dict[str, str]:
    token = mint_service_token(
        dev_service_signer(), service="agents", audience="tools", tenant_id=tenant, scopes=["tools:view"], team_id=team
    )
    return {"Authorization": f"Bearer {token}"}


async def test_a_call_on_an_app_the_team_has_off_names_the_app_and_team(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, _, _, _), _ = desk_rig
    await _sites_on(c, tenant)  # on for Operations only
    body = {"tool": "fields_sites_get_record", "input": {"id": "rec-1"}, "key": "k1", "runContext": {"act": "test"}}
    refused = await c.post("/v1/calls", json=body, headers=run_in(tenant, SECURITY))
    assert refused.status_code == 403, refused.text
    error = refused.json()["error"]
    assert error["code"] == "APP_OFF_FOR_TEAM", error
    assert {k: error["details"].get(k) for k in ("app", "appId", "teamId")} == {
        "app": "Sites desk",
        "appId": SITES,
        "teamId": SECURITY,
    }, error


def test_an_app_the_install_does_not_load_stays_a_different_refusal() -> None:
    module = {"display_name": "Gone desk", "plugin_off": "Gone desk isn't installed on this system."}
    refused = _before_policy(Resolved("read", "plugin", module, {"name": "gone_get", "enabled": True}), {})
    assert refused is not None and refused[1] == "PLUGIN_DISABLED" and refused[3] == {}, refused
