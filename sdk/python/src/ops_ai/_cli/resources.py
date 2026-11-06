"""`ops resources` over the public SDK: list an app's resources, preview adding some, add one to the team, take the
app's newer template into the team's copy, remove the copy. A resource is named by its id as `list` shows it."""

from __future__ import annotations

import argparse
from typing import Any

from .common import client, emit, parser, payload, refuse, verb_options


def main(argv: list[str]) -> int:
    ap = parser("ops resources", "The agents, skills, workflows and document types an app brings to a team.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("list", parents=common, help="the app's resources and the team's copies").add_argument("app")
    plan = sub.add_parser(
        "plan", parents=common, help="preview adding resources: what each brings with it; nothing is made"
    )
    plan.add_argument("app")
    plan.add_argument("ids", nargs="+")
    add = sub.add_parser("add", parents=common, help="add a resource to the team as a copy")
    add.add_argument("app")
    add.add_argument("id")
    add.add_argument("--fields", help="the copy's fields: k=v,k=v, a JSON or YAML file, or - for standard input")
    update = sub.add_parser(
        "update", parents=common, help="take the app's current template as a new draft of the team's copy"
    )
    update.add_argument("app")
    update.add_argument("id")
    update.add_argument("--confirm", action="store_true", help="replace a copy the team has edited since")
    remove = sub.add_parser("remove", parents=common, help="delete the team's copy")
    remove.add_argument("app")
    remove.add_argument("id")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns)
    except Exception as exc:
        return refuse(exc)


def _item(rows: list[dict[str, Any]], app: str, rid: str) -> dict[str, Any]:
    found = next((r for r in rows if r.get("id") == rid), None)
    if found is None:
        raise ValueError(f"{app} brings no resource {rid}; `ops resources list {app}` names them")
    return found


def _dispatch(ns: argparse.Namespace) -> int:
    resources = client(ns).resources
    rows = resources.list(ns.app)
    if ns.verb == "list":
        return emit(ns, rows)
    if ns.verb == "plan":
        return emit(ns, resources.plan([_item(rows, ns.app, i) for i in ns.ids]))
    item = _item(rows, ns.app, ns.id)
    if ns.verb == "add":
        return emit(ns, resources.add(item, **payload(ns.fields)))
    if ns.verb == "update":
        return emit(ns, resources.update(item, confirm=ns.confirm))
    resources.remove(item)
    return emit(ns, {"removed": ns.id})
