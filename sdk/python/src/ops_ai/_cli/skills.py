"""`opsai skills`: list and show the team's skills, write one from a file, publish it, and search what its steps can
mention."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._client import SKILL_KEYS
from ops_ai._io import dump_definition, load_definition

from .common import client, emit, parser, refuse, table, verb_options

# Asked only when a skill is created; a saved skill keeps its own.
CREATE_ONLY = ("slug", "ownerTeam", "origin")


def as_file(skill: dict[str, Any]) -> dict[str, Any]:
    """A stored skill as the file `apply` reads: its newest version's content under the names a save takes."""
    content = dict(skill.get("content") or {})
    content["toolIds"] = [t["toolId"] for t in content.pop("tools", None) or []]
    body = {k: content[k] for k in SKILL_KEYS if content.get(k) not in (None, "", [], {})}
    return {"id": skill["id"], "slug": skill["slug"], "ownerTeam": skill["ownerTeam"], **body}


def _stored(ops: OpsAI, data: dict[str, Any]) -> dict[str, Any] | None:
    """The team's skill a file names: by `id`, else by `slug`, else by its exact name."""
    if data.get("id"):
        return dict(ops.skills.get(str(data["id"])))
    wanted = str(data.get("slug") or data.get("name") or "")
    for row in ops.skills.list(search=wanted) if wanted else ():
        if row.get("slug") == data.get("slug") or (not data.get("slug") and row.get("name") == data.get("name")):
            return dict(row)
    return None


def apply(ops: OpsAI, data: dict[str, Any], *, note: str = "") -> Any:
    """Creates the skill a file describes, or saves the file as the draft of the one it names."""
    fields = {k: data[k] for k in SKILL_KEYS if k in data}
    current = _stored(ops, data)
    if current is not None:
        return ops.skills.save_draft(str(current["id"]), fields, note=note, base_version=int(current["version"]))
    return ops.skills.create({**fields, **{k: data[k] for k in CREATE_ONLY if k in data}})


def made(skill: dict[str, Any]) -> str:
    """One line for the version a save or a publish request made: the newest version and its own state. The skill's
    `status` is that of its published version, which a new draft on top of it does not change."""
    newest = dict((skill.get("versions") or [{}])[0])
    version, state = newest.get("version", skill.get("version")), newest.get("state", skill.get("status"))
    return f"{skill['id']}  {skill['name']}  v{version}  {state}"


def main(argv: list[str]) -> int:
    ap = parser("opsai skills", "The team's skills: list, show, apply, export, publish, references.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    listing = sub.add_parser("list", parents=common, help="skills")
    listing.add_argument("--search")
    listing.add_argument("--id", action="append", help="only this one; repeat for several")
    sub.add_parser("show", parents=common, help="one of the skills").add_argument("id")
    applying = sub.add_parser("apply", parents=common, help="create a skill from a file, or save it as a draft")
    applying.add_argument("definition", help="a YAML or JSON file; ownerTeam is needed to create")
    applying.add_argument("--note", default="")
    export = sub.add_parser("export", parents=common, help="print a stored skill as a file apply reads")
    export.add_argument("id")
    export.add_argument("--format", default="yaml", choices=("yaml", "json"))
    publish = sub.add_parser("publish", parents=common, help="ask to publish the newest draft")
    publish.add_argument("id")
    publish.add_argument("--note", default="")
    refs = sub.add_parser("references", parents=common, help="what the skill's steps can mention with @")
    refs.add_argument("id")
    refs.add_argument("--search", default="")
    refs.add_argument("--kind", choices=("tool", "knowledge", "skill", "agent", "workflow"))
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    if ns.verb == "list":
        return table(ns, ops.skills.list(search=ns.search, ids=ns.id), "id", "name", "status", "liveAgents")
    if ns.verb == "show":
        return emit(ns, ops.skills.get(ns.id))
    if ns.verb == "apply":
        saved = apply(ops, load_definition(Path(ns.definition)), note=ns.note)
        return emit(ns, saved, text=made(saved))
    if ns.verb == "export":
        file = as_file(ops.skills.get(ns.id))
        return emit(ns, file, text=dump_definition(file, ns.format).rstrip())
    if ns.verb == "publish":
        asked = ops.skills.publish(ns.id, note=ns.note)
        return emit(ns, asked, text=made(asked))
    found = ops.skills.references(ns.search, for_skill=ns.id, kind=ns.kind)
    rows = [{"kind": g["kind"], **item} for g in found["groups"] for item in g["items"]]
    return table(ns, rows, "kind", "id", "label")
