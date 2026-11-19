"""`opsai templates` over the public SDK: what the team can start from, by kind, and installing one as the team's copy.
A template is named by its reference, `<source>:<id>`, as `list` shows it."""

from __future__ import annotations

import argparse

from .common import client, emit, parser, payload, refuse, verb_options


def main(argv: list[str]) -> int:
    ap = parser("opsai templates", "The agents, skills, workflows, guardrails and other parts a team can start from.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    lst = sub.add_parser("list", parents=common, help="the templates the team is offered, with the team's copies")
    lst.add_argument("--kind", help="one kind: agent, skill, workflow, guardrail, case_type, task_type, document_type")
    lst.add_argument("--source", help="one pack or app, as plugin:<id>")
    add = sub.add_parser("install", parents=common, help="add a template to the team as its own copy")
    add.add_argument("ref", help="the template, as <source>:<id>")
    add.add_argument("--kind", help="the template's kind, when it is not offered by a listed pack")
    add.add_argument("--fields", help="the copy's fields: k=v,k=v, a JSON or YAML file, or - for standard input")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace) -> int:
    templates = client(ns).templates
    if ns.verb == "list":
        return emit(ns, templates.list(kind=ns.kind, source=ns.source))
    return emit(ns, templates.install(ns.ref, kind=ns.kind, **payload(ns.fields)))
