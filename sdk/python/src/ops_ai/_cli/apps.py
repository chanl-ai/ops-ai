"""`opsai apps`: the Apps area. The catalog, one app's page, turning an app on as the Turn on window does, adding its
tools to the team, its accounts and your own sign-ins,
the sign-in link to connect an account (printed, for a browser to open), an account's test, and the auth configs
(the team's own app credentials)."""

from __future__ import annotations

import argparse
from typing import Any

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, table, verb_options


def main(argv: list[str]) -> int:
    ap = parser("opsai apps", "Apps, their accounts and tools.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    catalog = sub.add_parser("list", parents=common, help="the Apps page's cards")
    catalog.add_argument("--connected", action="store_true", help="only the connected ones")
    sub.add_parser("show", parents=common, help="one app's page: card, accounts, tools, latest calls").add_argument(
        "app"
    )
    on = sub.add_parser("on", parents=common, help="turn an app on for the team and print the sign-in link")
    on.add_argument("app")
    on.add_argument(
        "--place", help="where the team signs in (the app's sign-in address); the app's default when left out"
    )
    on.add_argument("--whose", choices=sorted(WHOSE), default="each", help="whose account tools use (default: each)")
    on.add_argument("--no-assistant", action="store_true", help="leave the team's assistant without the read tools")
    add = sub.add_parser("add-tool", parents=common, help="add tools of an app to the team")
    add.add_argument("app")
    add.add_argument("tools", nargs="+")
    sub.add_parser("accounts", parents=common, help="an app's accounts and what each points at").add_argument("app")
    default = sub.add_parser("default", parents=common, help="make an account the team's default, or yours")
    default.add_argument("app")
    default.add_argument("account", help="the account's name")
    default.add_argument("--mine", action="store_true", help="your own default among your own sign-ins")
    sub.add_parser(
        "mine",
        parents=common,
        help="your own sign-ins on every app, one row per account (opsai connectors: one per app)",
    )
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


def _points_at(account: dict[str, Any]) -> str:
    """What tells an account apart, as its row's identity shows it: "eu.my.salesforce.com · signed in as …"."""
    return " · ".join(str(e.get("shown")) for e in account.get("identity") or [])


def _make_default(ns: argparse.Namespace, ops: OpsAI) -> int:
    """The account named `ns.account` becomes the team's default, or with --mine the caller's own default. The name is
    matched by the service (GET /v1/apps/{app}/accounts?name=), so it compares as calls compare it."""
    found = ops.raw.tools.apps_list_account_choices(ns.app, name=ns.account, mine=True if ns.mine else None)
    if not found:
        raise ValueError(f"{ns.app} has no account named {ns.account} you may use.")
    account_id = str(found[0]["id"])
    if ns.mine:
        done = ops.raw.tools.apps_pin_default(ns.app, account_id)
    else:
        done = ops.raw.tools.apps_make_team_default(ns.app, account_id)
    whose = "your" if ns.mine else "the team's"
    return emit(ns, done, text=f"{found[0]['name']} is now {whose} default.")


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        cards = ops.apps.list(connected=True if ns.connected else None)
        return table(ns, cards, "id", "name", "kindLabel", "status", "toolsCount", "accountsCount")
    if ns.verb == "show":
        return emit(ns, ops.apps.get(ns.app))
    if ns.verb == "on":
        return _turn_on(ns, ops)
    if ns.verb == "add-tool":
        return table(ns, ops.raw.tools.apps_add_tools(ns.app, {"tools": ns.tools}), "name", "title", "added")
    if ns.verb == "accounts":
        page = ops.apps.get(ns.app)
        rows = [{**a, "pointsAt": _points_at(a)} for a in page.get("accounts") or []]
        return table(ns, rows, "id", "name", "pointsAt", "kind", "state", "default", "configName")
    if ns.verb == "default":
        return _make_default(ns, ops)
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


# The window's "Whose account do tools use?": each person's own with the team account for runs nobody started, the
# team account only, or each person only.
WHOSE = {"each": "person_or_team", "team": "team", "person": "person"}


def _turn_on(ns: argparse.Namespace, ops: OpsAI) -> int:
    """The Turn on window from the terminal: the app on with its read tools added, the assistant given them unless
    asked not to, and the team account's sign-in link, which a browser opens to finish."""
    fields: dict[str, Any] = {"signIn": WHOSE[ns.whose]}
    if ns.place:
        fields["settings"] = {"login_url": ns.place}
    card = ops.apps.turn_on(ns.app, **fields)
    given = None if ns.no_assistant else ops.apps.give_assistant(ns.app)
    start = ops.accounts.connect(ns.app, account=card.get("connectionId"), team=True)
    lines = [f"Turned on {card.get('name')}: {card.get('toolsAdded') or 0} read tools added."]
    if given is not None:
        lines.append(_given(given))
    lines.append(_link(start))
    return emit(ns, {"card": card, "assistant": given, "signIn": start}, text="\n".join(lines))


def _given(given: dict[str, Any]) -> str:
    """What the assistant got, in words, by the route's state."""
    name = given.get("agentName")
    return {
        "given": f"{name} can use them now.",
        "already": f"{name} already had them.",
        "in_review": f"{name} gets them once its new version is approved in Reviews.",
        "waiting": f"{name} has a draft or a review open, so it was left as it is; add the tools on its Tools tab.",
        "none": "The app has no read tools to give.",
    }.get(str(given.get("state")), f"{name}: {given.get('state')}")


def _link(start: dict[str, Any]) -> str:
    """The sign-in link a person opens; the sign-in finishes on its return page, as from the console."""
    return f"Open to sign in: {start.get('authorizeUrl')}\n(returns to {start.get('redirectUri')})"
