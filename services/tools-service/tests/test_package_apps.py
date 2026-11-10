"""A package app's call (a plugin with `connection.runs_on`), by failure mode: it signs in with no account, or with
the package's own binding instead of the chosen account of the app it runs on; it runs while that app is off for the
team; a name keyed by the package, or another app's account, picks something; and it runs on an account where the
package is missing, or refuses one that was never checked."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ops_plugin_sdk.loader import discover
from ops_store import isolation
from ops_tools.gateway_calls import _before_policy  # pyright: ignore[reportPrivateUsage]
from ops_tools.plugins.host import module_id_of
from ops_tools.registry import Resolved

from .test_my_connectors import SITES, _second, _signed_in, _sites_on  # pyright: ignore[reportPrivateUsage]
from .test_plugin_manifest_fields import (  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures
    TEAM,
    ZOOM,
    ZOOM_SECRET,
    TokenDesk,
    admin,
    desk_rig,  # pyright: ignore[reportUnusedImport]
    turn_on,
)

LOANS = "test.packages-loans"
EU = "Sites · second org"
FOLDER = Path(__file__).parent / "plugin_packages"
OP = {"name": "packages_loans_get_loan", "enabled": True, "input": []}


async def _rig(rig: tuple[Any, TokenDesk], tenant: str) -> tuple[Any, Any, Any, str, str]:
    """Sites desk on with two signed-in accounts at two sites (the second is EU), and the loan package on."""
    (c, host, store, _), _ = rig
    host.loaded.extend(discover(found=[], folders=[str(FOLDER / "packages_loans")]))
    first = await _sites_on(c, tenant)
    second = await _second(c, tenant, first)
    for conn, site in ((first, "s-home"), (second, "s-eu")):
        await _signed_in(store, tenant, conn, f"ops@{site}.example")
        await store.set_plugin_settings(tenant, conn, {"site_id": site})
    on = await turn_on(c, tenant, LOANS)
    assert on.status_code == 200, on.text
    await host.ensure(tenant, datetime.now(UTC))
    return c, host, store, first, second


async def _seen(host: Any, tenant: str, **kw: Any) -> dict[str, Any]:
    module = await host.store.get(tenant, module_id_of(host.plugins[LOANS].manifest))
    assert module is not None
    with isolation.scope(tenant, TEAM):
        return dict(await host.for_call(tenant, TEAM, module, "live", **kw))


def _refusal(seen: dict[str, Any]) -> str | None:
    refused = _before_policy(Resolved("read", "plugin", seen, OP), {})
    return refused[1] if refused else None


async def test_a_package_call_signs_in_with_the_chosen_account_of_the_app_it_runs_on(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    _, host, _, first, second = await _rig(desk_rig, tenant)
    default = await _seen(host, tenant)
    assert default["connection_id"] == first and default["endpoint"].endswith("/sites/s-home/loans-api"), default
    named = await _seen(host, tenant, accounts={SITES: EU})
    assert named["connection_id"] == second, named
    assert named["endpoint"] == "https://api.multi.test/sites/s-eu/loans-api", named
    assert named["egress_hosts"] == ["api.multi.test"], named


async def test_a_package_is_off_while_the_app_it_runs_on_is_off(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    c, host, _, _, _ = await _rig(desk_rig, tenant)
    off = await c.put(f"/v1/apps/{SITES}/team", json={"enabled": False}, headers=admin(tenant))
    assert off.status_code == 200, off.text
    seen = await _seen(host, tenant)
    assert seen.get("plugin_off") and "Sites desk" in str(seen["plugin_off"]), seen
    assert seen["connection_id"] is None, seen


@pytest.mark.parametrize("accounts", [{f"plugin:{LOANS}": EU}, {SITES: "Desk main"}])
async def test_a_package_never_picks_an_account_outside_the_app_it_runs_on(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
    accounts: dict[str, str],
) -> None:
    c, host, _, _, _ = await _rig(desk_rig, tenant)
    desk = await turn_on(c, tenant, "test.fields-zoom", client=(ZOOM, ZOOM_SECRET), accountName="Desk main")
    assert desk.status_code == 200, desk.text
    seen = await _seen(host, tenant, accounts=accounts)
    assert _refusal(seen) == "ACCOUNT_NOT_FOUND" and seen["connection_id"] is None, seen


async def test_a_package_is_refused_on_an_account_where_it_is_missing_and_runs_where_unchecked(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    c, host, store, first, second = await _rig(desk_rig, tenant)
    unchecked = await _seen(host, tenant)
    assert _refusal(unchecked) is None and unchecked["connection_id"] == first, unchecked
    await store.set_health(tenant, first, {"status": "ok", "packages": {LOANS: {"missing": ["LNDK__Loan__c"]}}})
    await store.set_health(tenant, second, {"status": "ok", "packages": {LOANS: {"missing": []}}})
    missing = await _seen(host, tenant)
    assert _refusal(missing) == "PACKAGE_MISSING" and missing["connection_id"] is None, missing
    assert "Loan desk" in str(missing["package_missing"]), missing
    there = await _seen(host, tenant, accounts={SITES: EU})
    assert _refusal(there) is None and there["connection_id"] == second, there
    picker = await c.get(f"/v1/apps/plugin:{LOANS}/accounts?usable=1", headers=admin(tenant))
    assert picker.status_code == 200, picker.text
    rows = {r["id"]: r for r in picker.json()["data"]}
    assert rows[first]["missingObjects"] == ["LNDK__Loan__c"] and rows[second]["missingObjects"] == [], rows
    assert {r["appId"] for r in rows.values()} == {SITES}, rows


async def test_the_package_check_lists_each_required_object_at_the_accounts_own_address(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    _, host, _, _, second = await _rig(desk_rig, tenant)
    checks = await host.package_checks(tenant, second)
    assert checks == [
        {"id": LOANS, "title": "Loan desk", "paths": {"LNDK__Loan__c": "/sites/s-eu/objects/LNDK__Loan__c"}}
    ], checks
