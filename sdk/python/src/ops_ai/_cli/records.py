"""`opsai cases`, `opsai files` and `opsai documents`: cases as the Cases page lists them, with a note added to one;
files as the Files page holds them, and an upload through the same ticket, bytes and complete steps; document types and
what was read from a file."""

from __future__ import annotations

import argparse
import json
import mimetypes
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._transport import every_page

from .common import client, emit, marked, parser, refuse, table, verb_options


def _area(prog: str, text: str) -> tuple[argparse.ArgumentParser, Any, list[argparse.ArgumentParser]]:
    ap = parser(prog, text)
    return ap, ap.add_subparsers(dest="verb", required=True), [verb_options()]


def cases_main(argv: list[str]) -> int:
    ap, sub, common = _area("opsai cases", "Cases: list, show, add a note.")
    listing = sub.add_parser("list", parents=common, help="cases")
    listing.add_argument("--status", action="append")
    listing.add_argument("--search")
    types = sub.add_parser("types", parents=common, help="the case types a team defines")
    types.add_argument("--search")
    sub.add_parser("show", parents=common, help="one case").add_argument("case")
    note = sub.add_parser("note", parents=common, help="add a note to a case's timeline")
    note.add_argument("case")
    note.add_argument("text")
    ns = ap.parse_args(argv)
    try:
        ops = client(ns)
        cases = ops.raw.agents
        if ns.verb == "list":
            rows = ops.cases.list(status=ns.status, search=ns.search)
            return table(ns, rows, "id", "subject", "status", "priority", "assignee", "customerName")
        if ns.verb == "types":
            return table(ns, ops.case_types.list(search=ns.search), "id", "name", "description")
        if ns.verb == "show":
            return emit(ns, cases.cases_get_case(ns.case))
        return emit(ns, cases.cases_add_event(ns.case, {"kind": "note", "text": ns.text}))
    except Exception as exc:
        return refuse(exc)


def files_main(argv: list[str]) -> int:
    ap, sub, common = _area("opsai files", "Files: list, show, upload.")
    listing = sub.add_parser("list", parents=common, help="files")
    listing.add_argument("--search")
    listing.add_argument("--purpose", action="append")
    sub.add_parser("show", parents=common, help="one file").add_argument("file")
    upload = sub.add_parser("upload", parents=common, help="upload a file; the same bytes again answer the stored one")
    upload.add_argument("path")
    upload.add_argument("--purpose", required=True, help="what it is for, e.g. case_attachment or knowledge_source")
    sub.add_parser("limits", parents=common, help="each purpose's allowed types and size")
    watch = sub.add_parser("watch", help="watched folders: list, show, add, check, events, delete")
    wsub = watch.add_subparsers(dest="watch_verb", required=True)
    wsub.add_parser("list", parents=common, help="the team's watched folders with their last check")
    wsub.add_parser("show", parents=common, help="one watched folder").add_argument("watch")
    add = wsub.add_parser("add", parents=common, help="watch an app's folders; needs watches.manage")
    add.add_argument("name")
    add.add_argument("--plugin", required=True, help="the app's plugin, e.g. sharepoint")
    add.add_argument("--source", default="files", help="the plugin's file source (default files)")
    add.add_argument("--connection", help="the account to read with; the team account when left out")
    add.add_argument(
        "--values", required=True, help='the folders as JSON, e.g. {"site": "Finance", "libraries": ["Invoices"]}'
    )
    check = wsub.add_parser("check", parents=common, help="Check now; --wait waits for it to end")
    check.add_argument("watch")
    check.add_argument("--wait", type=float, default=0, help="seconds to wait for the check to end")
    events = wsub.add_parser("events", parents=common, help="what the checks found, oldest first")
    events.add_argument("watch")
    events.add_argument("--after", type=int, default=0)
    wsub.add_parser("delete", parents=common, help="stop watching; the files stay in Files").add_argument("watch")
    ns = ap.parse_args(argv)
    try:
        ops = client(ns)
        files = ops.raw.files
        if ns.verb == "watch":
            return _watch(ns, ops)
        if ns.verb == "list":
            rows = every_page(files.files_list_files, search=ns.search, purpose=ns.purpose)
            return table(ns, rows, "id", "name", "purpose", "size", "uploadedBy", "scan.status")
        if ns.verb == "show":
            return emit(ns, files.files_get_file(ns.file))
        if ns.verb == "limits":
            return emit(ns, files.files_upload_limits())
        return emit(ns, upload_file(ops, Path(ns.path), ns.purpose, marked(ns, Path(ns.path).name)))
    except Exception as exc:
        return refuse(exc)


def _watch(ns: Any, ops: OpsAI) -> int:
    watches = ops.files.watches
    if ns.watch_verb == "list":
        return table(ns, watches.list(), "id", "name", "plugin", "checking", "lastCheckAt", "lastCheck.status",
                     "lastCheck.brought", "lastCheck.failed")  # fmt: skip
    if ns.watch_verb == "show":
        return emit(ns, watches.get(ns.watch))
    if ns.watch_verb == "add":
        values = json.loads(ns.values)
        return emit(ns, watches.add(ns.name, plugin=ns.plugin, source=ns.source, values=values,
                                    connection_id=ns.connection))  # fmt: skip
    if ns.watch_verb == "check":
        return emit(ns, watches.check(ns.watch, wait=ns.wait))
    if ns.watch_verb == "events":
        return table(ns, watches.events(ns.watch, after=ns.after)["data"], "number", "kind", "path", "version",
                     "size", "reason")  # fmt: skip
    watches.delete(ns.watch)
    return emit(ns, {"deleted": ns.watch})


def upload_file(ops: OpsAI, path: Path, purpose: str, name: str | None = None) -> Any:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return ops.upload(name or path.name, path.read_bytes(), mime=mime, purpose=purpose)


def documents_main(argv: list[str]) -> int:
    ap, sub, common = _area("opsai documents", "Document types and what was read from files.")
    sub.add_parser("types", parents=common, help="the document types")
    sub.add_parser("type", parents=common, help="one document type").add_argument("type")
    reads = sub.add_parser("extractions", parents=common, help="what was read from files, newest first")
    reads.add_argument("--file", required=True, help="the file whose extractions to list")
    sub.add_parser("extraction", parents=common, help="one extraction").add_argument("extraction")
    ns = ap.parse_args(argv)
    try:
        docs = client(ns).raw.documents
        if ns.verb == "types":
            return table(ns, every_page(docs.document_types_list_types), "id", "name", "status", "liveVersion")
        if ns.verb == "type":
            return emit(ns, docs.document_types_get_type(ns.type))
        if ns.verb == "extractions":
            rows = every_page(docs.documents_file_extractions, file_id=ns.file)
            return table(ns, rows, "id", "fileId", "documentType", "status", "createdAt")
        return emit(ns, docs.documents_get_extraction(ns.extraction))
    except Exception as exc:
        return refuse(exc)
