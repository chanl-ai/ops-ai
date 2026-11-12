"""`opsai secrets`, `opsai egress` and `opsai policies`: the team's secrets (a value goes in and is never printed), the
hosts and address ranges tools may reach, and the policies a Security admin sets."""

from __future__ import annotations

import json
import sys

from .common import client, emit, parser, refuse, table, verb_options


def secrets_main(argv: list[str]) -> int:
    ap = parser("opsai secrets", "Secrets: list, create, rotate, rename, delete. A value is never printed.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("list", parents=common, help="the team's secrets, without values")
    for name in ("create", "rotate"):
        p = sub.add_parser(
            name, parents=common, help=f"{name} a secret; the value comes from --value or standard input"
        )
        p.add_argument("name")
        p.add_argument("--value")
    sub.add_parser("delete", parents=common, help="delete a secret").add_argument("name")
    rename = sub.add_parser("rename", parents=common, help="rename a secret")
    rename.add_argument("name")
    rename.add_argument("new_name")
    ns = ap.parse_args(argv)
    try:
        secrets = client(ns).secrets
        if ns.verb == "list":
            return table(ns, secrets.list(), "name", "teamId", "createdAt")
        if ns.verb in ("create", "rotate"):
            value = ns.value if ns.value is not None else sys.stdin.read().rstrip("\n")
            done = (secrets.create if ns.verb == "create" else secrets.rotate)(ns.name, value)
            return emit(ns, done)
        if ns.verb == "rename":
            return emit(ns, secrets.rename(ns.name, ns.new_name))
        return emit(ns, secrets.delete(ns.name))
    except Exception as exc:
        return refuse(exc)


def egress_main(argv: list[str]) -> int:
    ap = parser("opsai egress", "Egress: list, allow-host, allow-range, remove-host, remove-range.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("list", parents=common, help="what tools may reach")
    for name in ("allow-host", "allow-range"):
        p = sub.add_parser(name, parents=common, help="allow a host" if "host" in name else "allow an address range")
        p.add_argument("value")
        p.add_argument("--note", default="")
    for name in ("remove-host", "remove-range"):
        sub.add_parser(name, parents=common).add_argument("value")
    ns = ap.parse_args(argv)
    try:
        egress = client(ns).egress
        if ns.verb == "list":
            return emit(ns, egress.list())
        if ns.verb == "allow-host":
            return emit(ns, egress.allow_host(ns.value, ns.note))
        if ns.verb == "allow-range":
            return emit(ns, egress.allow_range(ns.value, ns.note))
        if ns.verb == "remove-host":
            return emit(ns, egress.remove_host(ns.value))
        return emit(ns, egress.remove_range(ns.value))
    except Exception as exc:
        return refuse(exc)


def policies_main(argv: list[str]) -> int:
    ap = parser(
        "opsai policies", "The team's policies: get, set. The value is JSON (true, false, a string, an object)."
    )
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("get", parents=common, help="one policy").add_argument("key")
    put = sub.add_parser("set", parents=common, help="change one policy for the team the command acts in")
    put.add_argument("key")
    put.add_argument("value", help="JSON, e.g. true")
    ns = ap.parse_args(argv)
    try:
        policies = client(ns).policies
        if ns.verb == "get":
            return emit(ns, policies.get(ns.key))
        return emit(ns, policies.set(ns.key, json.loads(ns.value)))
    except Exception as exc:
        return refuse(exc)
