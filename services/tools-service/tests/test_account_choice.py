"""Which of a person's accounts a call uses, by failure mode: with two accounts of one app connected and no default
chosen, a call quietly takes the newest, so a chat acts in an org the person did not mean; the refusal does not name
the accounts to choose from; and once the person saves a default, the call still asks, or runs as the other account."""

from __future__ import annotations

from typing import Any

from ops_store import isolation
from ops_tools.gateway_calls import _before_policy  # pyright: ignore[reportPrivateUsage]
from ops_tools.registry import Resolved
from ops_tools.store.modules import ModuleStore

from .test_my_connectors import PRIYA, SITES, _second, _signed_in, _sites_on  # pyright: ignore[reportPrivateUsage]
from .test_plugin_manifest_fields import (  # noqa: F401  # pyright: ignore[reportUnusedImport] - fixtures
    TEAM,
    TokenDesk,
    admin,
    desk_rig,  # pyright: ignore[reportUnusedImport]
)

MODULE = "mod_plugin_fields_sites"


async def _seen(host: Any, store: Any, tenant: str) -> dict[str, Any]:
    module = await ModuleStore(store.engine).get(tenant, MODULE)
    assert module is not None
    with isolation.scope(tenant, TEAM):
        return dict(await host.for_call(tenant, TEAM, module, "live", person=PRIYA))


async def test_two_accounts_and_no_default_ask_which_and_a_saved_default_runs_as_it(
    desk_rig: tuple[Any, TokenDesk],  # noqa: F811
    tenant: str,
) -> None:
    (c, host, store, _), _ = desk_rig
    first = await _sites_on(c, tenant)
    await _signed_in(store, tenant, first, "priya@live.example")
    one = await _seen(host, store, tenant)
    assert one.get("account_choice") is None and one["connection_id"] == first, "one account never asks"

    second = await _second(c, tenant, first)
    await _signed_in(store, tenant, second, "priya@second.example")
    both = await _seen(host, store, tenant)
    choice = both.get("account_choice")
    assert choice is not None, both
    op = {"name": "fields_sites_get_record", "enabled": True}
    refused = _before_policy(Resolved("read", "plugin", both, op), {"id": "rec-1"})
    assert refused is not None and refused[1] == "ACCOUNT_CHOICE_NEEDED", refused
    details = refused[3]
    assert (details["app"], details["appId"]) == ("Sites desk", SITES), details
    assert {(a["connectionId"], a["account"]) for a in details["accounts"]} == {
        (first, "priya@live.example"),
        (second, "priya@second.example"),
    }, details
    shown = [" · ".join(e["shown"] for e in a["identity"]) for a in details["accounts"]]
    assert all(shown) and len(set(shown)) == 2, "each account says where it points, and the two read apart"

    saved = await c.put(f"/v1/apps/{SITES}/accounts/{second}/default", headers=admin(tenant))
    assert saved.status_code == 200, saved.text
    chosen = await _seen(host, store, tenant)
    assert chosen.get("account_choice") is None and chosen["connection_id"] == second, chosen
