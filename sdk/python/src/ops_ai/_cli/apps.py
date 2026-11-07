"""`ops apps`: the Apps area. The catalog, one app's page, adding its tools to the team, its accounts and My accounts,
the sign-in link to connect an account (printed, for a browser to open), an account's test, and the auth configs
(the team's own app credentials)."""

from __future__ import annotations

import argparse
from typing import Any

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, table, verb_options


def main(argv: list[str]) -> int:
    ap = parser("ops apps", "Apps, their accounts and tools.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    catalog = sub.add_parser("list", parents=common, help="the Apps page's cards")
    catalog.add_argument("--connected", action="store_true", help="only the connected ones")
    sub.add_parser("show", parents=common, help="one app's page: card, accounts, tools, latest calls").add_argument(
        "app"
    )
    add = sub.add_parser("add-tool", parents=common, help="add tools of an app to the team")
    add.add_argument("app")
    add.add_argument("tools", nargs="+")
    sub.add_parser("accounts", parents=common, help="an app's accounts").add_argument("app")
    sub.add_parser("mine", parents=common, help="My accounts: your own sign-ins on every app")
    for name, text in (("connect", "print the sign-in link that connects an account"), ("test", "test an account")):
        p = sub.add_parser(name, parents=common, help=text)
        p.add_argument("app")
        p.add_argument("--account", help="the account's id; the app's default when left out")
        p.add_argument("--team-account", action="store_true", help="the team account, not your own")
    configs = sub.add_parser("auth-configs", parents=common, help="the team's app credentials")
    configs.add_argument("--app")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        cards = ops.apps.list(connected=True if ns.connected else None)
        return table(ns, cards, "id", "name", "kindLabel", "status", "toolsCount", "accountsCount")
    if ns.verb == "show":
        return emit(ns, ops.apps.get(ns.app))
    if ns.verb == "add-tool":
        return table(ns, ops.raw.tools.apps_add_tools(ns.app, {"tools": ns.tools}), "name", "title", "added")
    if ns.verb == "accounts":
        page = ops.apps.get(ns.app)
        return table(ns, page.get("accounts") or [], "id", "name", "kind", "state", "default", "configName")
    if ns.verb == "mine":
        return table(ns, ops.accounts.mine(), "connectionId", "app", "connection", "status", "signedInAs")
    if ns.verb == "connect":
        start = ops.accounts.connect(ns.app, account=ns.account, team=ns.team_account)
        return emit(ns, start, text=_link(start))
    if ns.verb == "test":
        done = ops.accounts.test(ns.app, account=ns.account, team=ns.team_account)
        return emit(ns, done, text=f"{done.get('status')} {done.get('message') or ''}".strip())
    if ns.verb == "auth-configs":
        rows = ops.raw.tools.apps_list_app_credentials(app=ns.app)
        return table(ns, rows, "id", "name", "appName", "type", "status", "accounts")
    return 2


def _link(start: dict[str, Any]) -> str:
    """The sign-in link a person opens; the sign-in finishes on its return page, as from the console."""
    return f"Open to sign in: {start.get('authorizeUrl')}\n(returns to {start.get('redirectUri')})"
