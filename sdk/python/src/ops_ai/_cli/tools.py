"""`ops tools`: the Tools page. Tool modules, one module, a run of one of an app's tools (Mock reaches nothing; Real is
the gateway's call with every check), and the tool-call log."""

from __future__ import annotations

import argparse

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .common import client, emit, parser, payload, refuse, table, verb_options


def main(argv: list[str]) -> int:
    ap = parser("ops tools", "Tools, test runs and the tool-call log.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="tool modules, or an app's tools with --app")
    listing.add_argument("--app")
    listing.add_argument("--search")
    sub.add_parser("show", parents=common, help="one tool module").add_argument("id")
    run = sub.add_parser("run", parents=common, help="run one of an app's tools; Mock unless --real")
    run.add_argument("app")
    run.add_argument("tool")
    run.add_argument("--input", help="the input: k=v,k=v, JSON, a file, or - for standard input")
    run.add_argument("--real", action="store_true", help="the real call, through every check")
    run.add_argument("--environment", help="production or test; a Real run is a test run when left out")
    calls = sub.add_parser("calls", parents=common, help="the tool-call log, newest first")
    calls.add_argument("--tool")
    calls.add_argument("--thread")
    calls.add_argument("--limit", type=int, default=20)
    sub.add_parser("call", parents=common, help="one logged tool call").add_argument("id")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        if ns.app:
            return table(ns, list(ops.tools.list(ns.app)), "name", "title", "access", "added")
        rows = page_items(ops.raw.tools.tool_modules_list_modules(page_size=50, search=ns.search))[0]
        return table(ns, rows, "id", "displayName", "type", "status", "operationCount")
    if ns.verb == "show":
        return emit(ns, ops.tools.get(ns.id))
    if ns.verb == "run":
        done = ops.tools.run(ns.app, ns.tool, payload(ns.input), real=ns.real, environment=ns.environment)
        return emit(ns, done)
    if ns.verb == "calls":
        rows = ops.usage.list(page=1, page_size=ns.limit, tool=ns.tool, thread=ns.thread)
        return table(ns, rows, "id", "at", "title", "outcome", "credential", "actingFor", "environment")
    if ns.verb == "call":
        return emit(ns, ops.raw.tools.executions_get_execution(ns.id))
    return 2
