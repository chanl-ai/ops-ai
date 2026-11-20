"""`opsai agents` over the public SDK: apply, publish, chat, test, trace, references and the publish check."""

from __future__ import annotations

import argparse

from ops_ai._agents import agent_file

from .common import client, emit, parser, refuse, verb_options

KINDS = ("tool", "knowledge", "skill", "agent", "workflow")


def main(argv: list[str]) -> int:
    ap = parser("opsai agents", "Author and chat with agents through the public SDK.")
    sub = ap.add_subparsers(dest="verb", required=True)
    # The connection options are also read after the verb, as the other nouns take them.
    common = [verb_options()]
    for name, help_text in (
        ("validate", "check a local agent file"),
        ("apply", "create or update a draft"),
    ):
        p = sub.add_parser(name, parents=common, help=help_text)
        p.add_argument("definition")
    export = sub.add_parser("export", parents=common, help="print a stored agent")
    export.add_argument("id")
    publish = sub.add_parser("publish", parents=common, help="request publish")
    publish.add_argument("id")
    publish.add_argument("--note", default="")
    for name in ("pause",):
        sub.add_parser(name, parents=common).add_argument("id")
    chat = sub.add_parser("chat", parents=common, help="send one message on the published agent")
    chat.add_argument("id")
    chat.add_argument("--message", required=True)
    run = sub.add_parser("run", parents=common, help="start the published agent in wait, stream or background")
    run.add_argument("id")
    run.add_argument("--message", required=True)
    run.add_argument("--mode", default="wait", choices=("wait", "stream", "background"))
    test = sub.add_parser("test", parents=common, help="run one test turn")
    test.add_argument("id")
    test.add_argument("--message", required=True)
    trace = sub.add_parser("trace", parents=common, help="recent runs")
    trace.add_argument("id")
    listing = sub.add_parser("list", parents=common, help="the team's agents")
    listing.add_argument("--search")
    options = sub.add_parser("tool-options", parents=common, help="the operations an agent may be granted")
    options.add_argument("--search")
    grant = sub.add_parser(
        "grant-tools", parents=common, help="add tools to an agent's draft, keeping the ones it holds"
    )
    grant.add_argument("id")
    grant.add_argument("tools", nargs="+", help="tool ids from tool-options")
    refs = sub.add_parser("references", parents=common, help="what the agent's brief can mention with @")
    refs.add_argument("id")
    refs.add_argument("--search", default="")
    refs.add_argument("--kind", choices=KINDS)
    add = sub.add_parser(
        "add-reference", parents=common, help="grant the agent something its brief mentions, as a new draft"
    )
    add.add_argument("id")
    add.add_argument("kind", choices=KINDS)
    add.add_argument("ref", help="the id of the tool, knowledge base, skill, agent or workflow")
    check = sub.add_parser("publish-check", parents=common, help="what stops the newest draft from being published")
    check.add_argument("id")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace) -> int:
    ops = client(ns)
    agents = ops.agents
    if ns.verb == "list":
        return emit(ns, list(agents.list(search=ns.search)))
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
    if ns.verb == "tool-options":
        return emit(ns, agents.tool_options(ns.search))
    if ns.verb == "grant-tools":
        return emit(ns, agents.grant_tools(ns.id, ns.tools))
    if ns.verb == "references":
        found = agents.references(ns.search, for_agent=ns.id, kind=ns.kind)
        return emit(ns, [{"kind": g["kind"], **item} for g in found["groups"] for item in g["items"]])
    if ns.verb == "add-reference":
        return emit(ns, agents.add_reference(ns.id, ns.kind, ns.ref))
    if ns.verb == "publish-check":
        return emit(ns, agents.publish_check(ns.id))
    return 2
