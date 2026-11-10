"""`opsai connectors`: Connectors (Mine), one row per app that acts as you, and Disconnect.

opsai connectors list                       # what each app can do as you, whom it signs in as, its state
opsai connectors disconnect GitHub          # ends your own sign-in on its primary account (--account for another)
"""

from __future__ import annotations

import argparse

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, table, verb_options


def main(argv: list[str]) -> int:
    ap = parser("opsai connectors", "Your connectors: one row per app that acts as you.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("list", parents=common, help="each app that acts as you, with its state and what it can do")
    end = sub.add_parser("disconnect", parents=common, help="end your own sign-in on an app")
    end.add_argument("app", help="the app's name or id")
    end.add_argument("--account", help="the account's id; the app's primary account when left out")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        return table(ns, ops.me.connectors.list(), "name", "appState", "account", "accountCount", "canDo")
    ops.me.connectors.disconnect(ns.app, account=ns.account)
    return emit(ns, {"disconnected": ns.app}, text=f"disconnected {ns.app}")
