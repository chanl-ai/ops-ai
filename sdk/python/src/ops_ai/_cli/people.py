"""`ops people` and `ops models`: the team's members and roles as Settings shows them, an invite (printed, not sent,
unless --send), and the models settings: the chat aliases an agent may name, the provider connections and keys, and
one test turn on an agent's model (it costs money, so it runs only with --confirm)."""

from __future__ import annotations

import argparse
import sys

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .chat import start_thread, turn
from .common import client, emit, parser, refuse, table, verb_options


def people_main(argv: list[str]) -> int:
    ap = parser("ops people", "Members, invites and roles.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="the team's members")
    listing.add_argument("--role", action="append")
    listing.add_argument("--status", action="append")
    invite = sub.add_parser("invite", parents=common, help="invite people to the team; prints the invite unless --send")
    invite.add_argument("emails", nargs="+")
    invite.add_argument("--role", required=True)
    invite.add_argument("--send", action="store_true", help="send the invites; without it nothing is sent")
    sub.add_parser("roles", parents=common, help="the roles and how many hold each")
    sub.add_parser("role", parents=common, help="one role and its permissions").add_argument("role")
    sub.add_parser("me", parents=common, help="who you are signed in as, and your teams")
    ns = ap.parse_args(argv)
    try:
        return _people(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _people(ns: argparse.Namespace, ops: OpsAI) -> int:
    platform = ops.raw.platform
    if ns.verb == "list":
        rows = page_items(platform.members_list_members(role=ns.role, status=ns.status))[0]
        return table(ns, rows, "name", "email", "role", "team", "status")
    if ns.verb == "invite":
        body = invite_body(ns.emails, ns.role)
        if not ns.send:
            return emit(ns, {"wouldSend": body}, text=f"Would invite {', '.join(ns.emails)} as {ns.role}; add --send")
        return emit(ns, platform.members_invite_members(body))
    if ns.verb == "roles":
        return table(ns, platform.roles_list_roles(), "id", "name", "assignmentCount", "permissionCount")
    if ns.verb == "role":
        return emit(ns, platform.roles_read_role(ns.role))
    return emit(ns, platform.me_me())


def invite_body(emails: list[str], role: str) -> dict[str, object]:
    return {"emails": list(emails), "role": role}


def models_main(argv: list[str]) -> int:
    ap = parser("ops models", "Model aliases, provider connections and keys, and one test turn.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("aliases", parents=common, help="the chat aliases an agent may name, with their prices")
    sub.add_parser("providers", parents=common, help="the provider connections (account admins)")
    sub.add_parser("keys", parents=common, help="the provider keys by name (account admins); no value is shown")
    test = sub.add_parser("test", parents=common, help="one test turn on an agent's model, as its Test panel")
    test.add_argument("agent", help="the agent's id, slug or name")
    test.add_argument("-m", "--message", default="What is 2 + 2?")
    test.add_argument("--confirm", action="store_true", help="spend a real model call")
    ns = ap.parse_args(argv)
    if ns.verb == "test" and not ns.confirm:
        sys.stderr.write("ops models test calls a real model, which costs money; add --confirm to run it\n")
        return 2
    try:
        return _models(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _models(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "aliases":
        return table(ns, ops.models.aliases(), "name", "clearedSensitivity", "inputPerMillion", "outputPerMillion")
    if ns.verb == "providers":
        return table(ns, ops.models.providers(), "id", "type", "baseUrl", "keyRef", "region")
    if ns.verb == "keys":
        return table(ns, ops.models.keys(), "name", "updatedAt", "updatedBy")
    ns.kb, ns.test, ns.thread = None, True, None
    thread = start_thread(ns, ops)
    seen = turn(ns, ops, thread, ns.message)
    if ns.as_json:
        return emit(ns, {"thread": thread, **seen})
    return 1 if seen["error"] else 0
