"""`opsai agents` over the public SDK: apply, publish, chat, test, trace, references and the publish check."""

from __future__ import annotations

import argparse

from ops_ai._agents import agent_file
from ops_ai._io import load_data

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
    sub.add_parser("sections", parents=common, help="the workspace's instruction section list")
    apply_sections = sub.add_parser(
        "sections-apply", parents=common, help="replace the workspace's instruction section list from a file"
    )
    apply_sections.add_argument("file")
    sub.add_parser("sections-reset", parents=common, help="bring the default instruction section list back")
    check = sub.add_parser("publish-check", parents=common, help="what stops the newest draft from being published")
    check.add_argument("id")
    evals = sub.add_parser(
        "eval",
        parents=common,
        help="run the agent's eval cases; exit 0 passing, 1 blocked (or a case failed with --cases), 2 could not run",
        description=(
            "Without --cases, runs the saved cases on the newest version and keeps the run. Exit 0 when the "
            "publish gate is open, 1 when a blocking step failed, 2 when the run could not happen (no model, "
            "not found, not allowed). With --cases FILE, scores the cases in the file and keeps nothing: exit 0 "
            "when every case passes, 1 when any fails."
        ),
    )
    evals.add_argument("id")
    evals.add_argument("--cases", metavar="FILE", help="score the cases in this JSON or YAML file instead")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc, refused=2 if ns.verb == "eval" else 1)


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
    if ns.verb == "sections":
        return emit(ns, agents.instruction_sections())
    if ns.verb == "sections-apply":
        return emit(ns, agents.set_instruction_sections(load_data(ns.file)))
    if ns.verb == "sections-reset":
        return emit(ns, agents.reset_instruction_sections())
    if ns.verb == "publish-check":
        return emit(ns, agents.publish_check(ns.id))
    if ns.verb == "eval":
        return _eval(ns, agents)
    return 2


def _outcome(result: dict) -> tuple[bool, str]:
    """Whether a case passed on the draft, and the reasons of its failed checks (a judge's reason when it judged)."""
    draft = result["draft"]
    why = "; ".join(
        f"{c['label']}: {c['reason']}" if c.get("reason") else c["label"]
        for c in draft.get("checks", [])
        if c.get("status") == "fail"
    )
    return draft["status"] == "pass", why


def _eval(ns: argparse.Namespace, agents) -> int:
    """Exit codes are the CI contract: 0 gate open, 1 gate blocked (read from the reply's `gate.blocked`, never
    decided here), 2 the run could not happen (raised, so `refuse` answers it)."""
    scored = ns.cases is not None
    run = agents.eval(ns.id, load_data(ns.cases)) if scored else agents.eval(ns.id, trigger="cli")
    results = run.get("results", [])
    passed = [_outcome(r)[0] for r in results]
    gate = run.get("gate") or {"blocked": False, "steps": []}
    failed = not all(passed) if scored else bool(gate["blocked"])
    if ns.as_json:
        emit(ns, run)
        return 1 if failed else 0
    summary = run.get("summary", {})
    lines = []
    for r in results:
        ok, why = _outcome(r)
        lines.append(f"{'pass' if ok else 'fail'}  {r['caseName']}" + (f"  ({why})" if why else ""))
    lines.append(f"pass rate: {summary.get('passed', 0)} of {summary.get('total', 0)}")
    lines.append(f"regressions: {summary.get('regressions', 0)}")
    lines.append(f"cost: ${run.get('costUsd', 0):.4f}" + (" (some calls unpriced)" if run.get("unpriced") else ""))
    if not scored:
        for step in gate["steps"]:
            lines.append(f"gate {step['label']} [{step['mode']}] {step['result']}: {step['detail']}")
        lines.append("gate: " + ("BLOCKED" if gate["blocked"] else "open"))
    code = 1 if failed else 0
    emit(ns, run, text="\n".join(lines))
    return code
