"""`opsai cases`, `opsai files` and `opsai documents`: cases as the Cases page lists them, with a note added to one;
files as the Files page holds them, and an upload through the same ticket, bytes and complete steps; document types and
what was read from a file."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .common import client, emit, marked, parser, refuse, table, verb_options


def _area(prog: str, text: str) -> tuple[argparse.ArgumentParser, Any, list[argparse.ArgumentParser]]:
    ap = parser(prog, text)
    return ap, ap.add_subparsers(dest="verb", required=True), [verb_options()]


def cases_main(argv: list[str]) -> int:
    ap, sub, common = _area("opsai cases", "Cases: list, show, add a note.")
    listing = sub.add_parser("list", parents=common, help="cases")
    listing.add_argument("--status", action="append")
    listing.add_argument("--search")
    sub.add_parser("show", parents=common, help="one case").add_argument("case")
    note = sub.add_parser("note", parents=common, help="add a note to a case's timeline")
    note.add_argument("case")
    note.add_argument("text")
    ns = ap.parse_args(argv)
    try:
        ops = client(ns)
        cases = ops.raw.agents
        if ns.verb == "list":
            rows = page_items(cases.cases_list_cases(status=ns.status, search=ns.search, page_size=50))[0]
            return table(ns, rows, "id", "subject", "status", "priority", "assignee", "customerName")
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
    ns = ap.parse_args(argv)
    try:
        ops = client(ns)
        files = ops.raw.files
        if ns.verb == "list":
            rows = page_items(files.files_list_files(search=ns.search, purpose=ns.purpose, page_size=50))[0]
            return table(ns, rows, "id", "name", "purpose", "size", "uploadedBy", "scan.status")
        if ns.verb == "show":
            return emit(ns, files.files_get_file(ns.file))
        if ns.verb == "limits":
            return emit(ns, files.files_upload_limits())
        return emit(ns, upload_file(ops, Path(ns.path), ns.purpose, marked(ns, Path(ns.path).name)))
    except Exception as exc:
        return refuse(exc)


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
            return table(ns, page_items(docs.document_types_list_types())[0], "id", "name", "status", "liveVersion")
        if ns.verb == "type":
            return emit(ns, docs.document_types_get_type(ns.type))
        if ns.verb == "extractions":
            rows = page_items(docs.documents_file_extractions(file_id=ns.file, page_size=50))[0]
            return table(ns, rows, "id", "fileId", "documentType", "status", "createdAt")
        return emit(ns, docs.documents_get_extraction(ns.extraction))
    except Exception as exc:
        return refuse(exc)
