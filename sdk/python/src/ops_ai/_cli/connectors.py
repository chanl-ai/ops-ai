"""`opsai connectors`: Connectors (Mine), one row per app that acts as you, and Disconnect.

opsai connectors list                       # what each app can do as you, whom it signs in as, its state
opsai connectors connect GitHub             # prints the address to open to sign in as you (--link for a connect link)
opsai connectors finish --state S --code C  # finishes that sign-in with what the browser came back with
opsai connectors accounts                   # your own accounts on every app
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
    start = sub.add_parser("connect", parents=common, help="start a sign-in and print the address to open")
    start.add_argument("app", nargs="?", help="the app's name or id; leave out with --link")
    start.add_argument("--link", help="the connect link a call for you was answered with")
    start.add_argument("--account", help="the account's id; the app's primary account when left out")
    done = sub.add_parser("finish", parents=common, help="finish a sign-in with what the browser came back with")
    done.add_argument("--state", required=True, help="the state in the address the browser returned to")
    done.add_argument("--code", help="the code in that address")
    done.add_argument("--error", help="the error in that address, when the sign-in was refused")
    sub.add_parser("accounts", parents=common, help="your own accounts on every app")
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
    if ns.verb == "connect":
        started = ops.me.connectors.connect(ns.app, link=ns.link, account=ns.account)
        return emit(ns, started, text=started["authorizeUrl"])
    if ns.verb == "finish":
        return emit(ns, ops.me.connectors.finish(ns.state, ns.code, error=ns.error), text="signed in")
    if ns.verb == "accounts":
        return table(ns, ops.me.connectors.accounts(), "app", "connection", "account", "connected", "connectionStatus")
    ops.me.connectors.disconnect(ns.app, account=ns.account)
    return emit(ns, {"disconnected": ns.app}, text=f"disconnected {ns.app}")
