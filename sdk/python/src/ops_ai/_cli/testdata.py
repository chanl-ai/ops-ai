"""`ops test-data clean`: finds what test runs made, by the `[test] ` prefix they put in a title or file name
(common.MARK), and removes it through the console's own delete routes, signed in as each item's owner. It lists and
removes nothing else: an item without the prefix, or one another person owns, is never touched. Without `--confirm`
it only lists. Dev seed people on a local stack only, since the sign-in is `--as`.

Kinds it removes: chat conversations (the chat list's and the agent Test panel's) and uploaded files. Case notes,
run records and knowledge pages have no delete route, so they stay."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any, cast

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .common import MARK, _seed, dev_client, dev_email, emit, parser, refuse, short, verb_options

PAGE = 100


def main(argv: list[str]) -> int:
    ap = parser("ops test-data", "Find and remove what test runs made.")
    sub = ap.add_subparsers(dest="verb", required=True)
    clean = sub.add_parser("clean", parents=[verb_options()], help="list marked test data; --confirm removes it")
    clean.add_argument(
        "--people", nargs="+", help="whose data: dev roles, names or emails; every seeded person if left out"
    )
    clean.add_argument("--since", help="only items made at or after this time, e.g. 2026-11-07")
    clean.add_argument("--confirm", action="store_true", help="remove what is listed")
    ns = ap.parse_args(argv)
    try:
        return _clean(ns)
    except Exception as exc:
        return refuse(exc)


def person_client(ns: argparse.Namespace, who: str) -> OpsAI:
    return dev_client(argparse.Namespace(as_role=who, base_url=ns.base_url, team=ns.team))


def _everyone() -> list[str]:
    return [str(p["email"]) for p in json.loads((_seed() / "people.json").read_text())["people"]]


def _new(item: dict[str, Any], key: str, since: str | None) -> bool:
    return since is None or str(item.get(key) or "") >= since


def _pages(fetch: Callable[[int], Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, 50):
        items = page_items(fetch(page))[0]
        rows.extend(cast(list[dict[str, Any]], items))
        if len(items) < PAGE:
            break
    return rows


def found(ops: OpsAI, email: str, since: str | None) -> list[tuple[str, dict[str, Any]]]:
    """This person's marked items, by kind: their own conversations and the files they uploaded."""
    out: list[tuple[str, dict[str, Any]]] = []
    for test in (False, True):
        rows = _pages(lambda p, test=test: ops.chat.threads(page=p, pageSize=PAGE, test=test))
        out += [("chat", t) for t in rows if str(t.get("title") or "").startswith(MARK) and _new(t, "createdAt", since)]
    files = _pages(lambda p: ops.raw.files.files_list_files(search=MARK.strip(), page=p, page_size=PAGE))
    out += [
        ("file", f)
        for f in files
        if str(f.get("name") or "").startswith(MARK) and f.get("uploadedBy") == email and _new(f, "uploadedAt", since)
    ]
    return out


def _remove(ops: OpsAI, kind: str, item: dict[str, Any]) -> None:
    if kind == "chat":
        ops.chat.remove(str(item["id"]))
    else:
        ops.raw.files.files_delete_file(str(item["id"]))


def _clean(ns: argparse.Namespace) -> int:
    people = [dev_email(w) for w in ns.people] if ns.people else _everyone()
    seen: list[dict[str, Any]] = []
    for email in people:
        ops = person_client(ns, email)
        for kind, item in found(ops, email, ns.since):
            row = {"kind": kind, "owner": email, "id": item["id"], "name": item.get("title") or item.get("name")}
            if ns.confirm:
                try:
                    _remove(ops, kind, item)
                    row["removed"] = True
                except Exception as exc:
                    row["removed"], row["error"] = False, str(exc)
            seen.append(row)
    emit(ns, seen, text=_report(seen, ns.confirm))
    return 1 if any(r.get("error") for r in seen) else 0


def _report(rows: list[dict[str, Any]], confirm: bool) -> str:
    if not rows:
        return "No marked test data found."
    lines = []
    for kind, label in (("chat", "chat conversations"), ("file", "files")):
        group = [r for r in rows if r["kind"] == kind]
        if group:
            lines.append(f"{label} ({len(group)})")
            for r in group:
                state = "" if not confirm else (" removed" if r.get("removed") else f" NOT removed: {r.get('error')}")
                lines.append(f"  {r['owner']}  {r['id']}  {short(r['name'] or '', 70)}{state}")
    if not confirm:
        lines.append(f"Nothing removed; CONFIRM=1 (--confirm) removes these {len(rows)}.")
    return "\n".join(lines)
