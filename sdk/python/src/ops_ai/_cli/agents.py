"""`opsai agents` over the public SDK: apply, publish, chat, test, trace."""

from __future__ import annotations

import argparse

from ops_ai._agents import agent_file

from .common import client, emit, parser, refuse


def main(argv: list[str]) -> int:
    ap = parser("opsai agents", "Author and chat with agents through the public SDK.")
    sub = ap.add_subparsers(dest="verb", required=True)
    for name, help_text in (
        ("validate", "check a local agent file"),
        ("apply", "create or update a draft"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("definition")
    export = sub.add_parser("export", help="print a stored agent")
    export.add_argument("id")
    publish = sub.add_parser("publish", help="request publish")
    publish.add_argument("id")
    publish.add_argument("--note", default="")
    for name in ("pause",):
        sub.add_parser(name).add_argument("id")
    chat = sub.add_parser("chat", help="send one message on the published agent")
    chat.add_argument("id")
    chat.add_argument("--message", required=True)
    run = sub.add_parser("run", help="start the published agent in wait, stream or background")
    run.add_argument("id")
    run.add_argument("--message", required=True)
    run.add_argument("--mode", default="wait", choices=("wait", "stream", "background"))
    test = sub.add_parser("test", help="run one test turn")
    test.add_argument("id")
    test.add_argument("--message", required=True)
    trace = sub.add_parser("trace", help="recent runs")
    trace.add_argument("id")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace) -> int:
    ops = client(ns)
    agents = ops.agents
    if ns.verb == "validate":
        return emit(ns, agents.validate(agent_file(ns.definition)))
    if ns.verb == "apply":
        return emit(ns, agents.apply(agent_file(ns.definition)))
    if ns.verb == "export":
        return emit(ns, agents.export(ns.id))
    if ns.verb == "publish":
        return emit(ns, agents.publish(ns.id, note=ns.note))
    if ns.verb == "pause":
        return emit(ns, agents.pause(ns.id))
    if ns.verb == "chat":
        return emit(ns, agents.chat(ns.id, ns.message))
    if ns.verb == "run":
        return emit(ns, agents.run(ns.id, ns.message, mode=ns.mode))
    if ns.verb == "test":
        return emit(ns, agents.test(ns.id, ns.message))
    if ns.verb == "trace":
        return emit(ns, agents.trace(ns.id))
    return 2
