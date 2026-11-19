"""`opsai skills`, `guardrails`, `widgets` and `threads`: the lists the Build and Work pages show, every page, with the
search each one has."""

from __future__ import annotations

import argparse
from collections.abc import Callable

from ops_ai import OpsAI

from .common import client, emit, parser, refuse, table, verb_options

# area -> (what it holds, the client noun, the columns of a row)
LISTS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "skills": ("skills", "skills", ("id", "name", "status", "liveAgents")),
    "guardrails": ("guardrails", "guardrails", ("id", "name", "status", "owner")),
    "widgets": ("widget templates", "widgets", ("widgetId", "name", "status", "version")),
}


def _list_area(area: str) -> Callable[[list[str]], int]:
    text, noun, columns = LISTS[area]

    def main(argv: list[str]) -> int:
        ap = parser(f"opsai {area}", f"The team's {text}: list, show.")
        sub = ap.add_subparsers(dest="verb", required=True)
        common = [verb_options()]
        listing = sub.add_parser("list", parents=common, help=text)
        listing.add_argument("--search")
        listing.add_argument("--id", action="append", help="only this one; repeat for several")
        sub.add_parser("show", parents=common, help=f"one of the {text}").add_argument("id")
        ns = ap.parse_args(argv)
        try:
            ops = client(ns)
            if ns.verb == "list":
                return table(ns, getattr(ops, noun).list(search=ns.search, ids=ns.id), *columns)
            return emit(ns, getattr(ops, noun).get(ns.id))
        except Exception as exc:
            return refuse(exc)

    return main


skills_main = _list_area("skills")
guardrails_main = _list_area("guardrails")
widgets_main = _list_area("widgets")


def threads_main(argv: list[str]) -> int:
    ap = parser("opsai threads", "Threads the caller may read: list, show, inbox.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="threads, newest update first")
    listing.add_argument("--graph", help="only this agent or workflow's threads")
    listing.add_argument("--id", action="append", help="only this one; repeat for several")
    sub.add_parser("show", parents=common, help="one thread's state").add_argument("thread")
    sub.add_parser("inbox", parents=common, help="a thread's channel messages").add_argument("thread")
    ns = ap.parse_args(argv)
    try:
        return _threads(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _threads(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        return table(ns, ops.threads.list(graph=ns.graph, ids=ns.id), "threadId", "graph", "status", "updatedAt")
    if ns.verb == "show":
        return emit(ns, ops.threads.get(ns.thread))
    return emit(ns, ops.threads.inbox(ns.thread))
