"""`opsai kb`: knowledge bases as the Knowledge pages show them. Bases and their documents, sources and their items,
adding a file or a written page, syncing, the playground's question, and the changes waiting on review."""

from __future__ import annotations

import argparse
import mimetypes
from pathlib import Path
from typing import Any

from ops_ai import OpsAI
from ops_ai._transport import page_items

from .common import client, emit, marked, parser, refuse, short, table, verb_options

PURPOSE = "knowledge_source"


def main(argv: list[str]) -> int:
    ap = parser("opsai kb", "Knowledge bases, sources, items, search and changes.")
    sub = ap.add_subparsers(dest="verb", required=True)
    common = [verb_options()]
    sub.add_parser("bases", parents=common, help="the knowledge bases").add_argument("--search")
    sub.add_parser("show", parents=common, help="one knowledge base").add_argument("kb")
    docs = sub.add_parser("documents", parents=common, help="a knowledge base's documents")
    docs.add_argument("kb")
    docs.add_argument("--search")
    sub.add_parser("sources", parents=common, help="the sources").add_argument("--search")
    sub.add_parser("source", parents=common, help="one source").add_argument("source")
    items = sub.add_parser("items", parents=common, help="a source's items")
    items.add_argument("source")
    items.add_argument("--search")
    create = sub.add_parser("create", parents=common, help="a knowledge base")
    create.add_argument("name")
    create.add_argument("--owner", help="the person who answers for it")
    add_source = sub.add_parser("add-source", parents=common, help="a source feeding knowledge bases")
    add_source.add_argument("name")
    add_source.add_argument("--kb", action="append", required=True, help="a knowledge base id; repeat for several")
    add_source.add_argument("--type", default="push", help="the source type; push takes items from `opsai kb push`")
    push = sub.add_parser("push", parents=common, help="put one item into a push source; the same item is unchanged")
    push.add_argument("source")
    push.add_argument("--name", required=True, help="the item's name in the source, e.g. fees/overdraft")
    push.add_argument("--title", required=True)
    push.add_argument("--text", required=True, help="the item's text, or @file to read it from a file")
    add_file = sub.add_parser("add-file", parents=common, help="upload files into a knowledge base and sync them")
    add_file.add_argument("kb")
    add_file.add_argument("paths", nargs="+")
    add_text = sub.add_parser("add-text", parents=common, help="a written page; the same title saves a new version")
    add_text.add_argument("kb")
    add_text.add_argument("--title", required=True)
    add_text.add_argument("--text", required=True, help="the page's text, or @file to read it from a file")
    sync = sub.add_parser("sync", parents=common, help="sync a source, or every source of a knowledge base")
    sync.add_argument("target", help="a source id (src_...) or a knowledge base id")
    sync.add_argument("--full", action="store_true", help="read every item again, not only what changed")
    search = sub.add_parser("search", parents=common, help="ask a knowledge base, as its Playground tab does")
    search.add_argument("kb")
    search.add_argument("question")
    changes = sub.add_parser("changes", parents=common, help="knowledge changes waiting on review")
    changes.add_argument("--kb")
    changes.add_argument("--view")
    sub.add_parser("change", parents=common, help="one knowledge change").add_argument("change")
    ns = ap.parse_args(argv)
    try:
        return _dispatch(ns, client(ns))
    except Exception as exc:
        return refuse(exc)


def _rows(found: Any) -> list[Any]:
    return page_items(found)[0]


def _dispatch(ns: argparse.Namespace, ops: OpsAI) -> int:
    kb = ops.raw.kb
    if ns.verb == "bases":
        rows = _rows(kb.knowledge_bases_list_knowledge_bases(page_size=50, search=ns.search))
        return table(ns, rows, "id", "name", "owner", "description")
    if ns.verb == "show":
        return emit(ns, kb.knowledge_bases_get_knowledge_base(ns.kb))
    if ns.verb == "documents":
        rows = _rows(kb.knowledge_bases_list_documents(ns.kb, page_size=50, search=ns.search))
        return table(ns, rows, "id", "title", "status", "sourceName")
    if ns.verb == "sources":
        return table(ns, _rows(kb.sources_list_sources(page_size=50, search=ns.search)), "id", "type", "name", "status")
    if ns.verb == "source":
        return emit(ns, kb.sources_get_source(ns.source))
    if ns.verb == "items":
        rows = _rows(kb.sources_list_items(ns.source, page_size=50, search=ns.search))
        return table(ns, rows, "id", "title", "status", "mime")
    if ns.verb == "create":
        return emit(ns, ops.knowledge.add_base(ns.name, owner=ns.owner))
    if ns.verb == "add-source":
        return emit(ns, ops.knowledge.add_source(ns.name, ns.kb, type=ns.type))
    if ns.verb == "push":
        text = Path(ns.text[1:]).read_text() if ns.text.startswith("@") else ns.text
        return emit(ns, ops.knowledge.push(ns.source, ns.name, title=ns.title, text=text))
    if ns.verb == "add-file":
        return emit(ns, add_files(ops, ns.kb, [Path(p) for p in ns.paths], ns))
    if ns.verb == "add-text":
        text = Path(ns.text[1:]).read_text() if ns.text.startswith("@") else ns.text
        return emit(ns, ops.knowledge.add_page(ns.kb, marked(ns, ns.title), text))
    if ns.verb == "sync":
        if ns.target.startswith("src_"):
            return emit(ns, kb.sources_sync_source(ns.target, {"full": ns.full}))
        return emit(ns, kb.knowledge_bases_refresh_knowledge_base(ns.target))
    if ns.verb == "search":
        answer = kb.knowledge_bases_query_knowledge_base(ns.kb, {"question": ns.question})
        return emit(ns, answer, text=_answer(answer))
    if ns.verb == "changes":
        rows = _rows(kb.changes_list_changes(page_size=50, kb_id=ns.kb, view=ns.view))
        return table(ns, rows, "id", "kind", "status", "title")
    if ns.verb == "change":
        return emit(ns, kb.changes_get_change(ns.change))
    return 2


def add_files(ops: OpsAI, kb: str, paths: list[Path], ns: argparse.Namespace | None = None) -> Any:
    """The knowledge base's Add files: each file uploaded to Files for knowledge, then added to the base's documents
    source, which syncs them."""
    ids = []
    for path in paths:
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        name = marked(ns, path.name) if ns is not None else path.name
        made = ops.upload(name, path.read_bytes(), mime=mime, purpose=PURPOSE)
        ids.append(str(made.get("id") or made.get("fileId")))
    return ops.raw.kb.knowledge_bases_add_documents(kb, {"fileIds": ids})


def _answer(answer: Any) -> str:
    if not isinstance(answer, dict):
        return short(answer, 400)
    lines = [str(answer.get("answer") or answer.get("text") or "").strip() or "(no answer)"]
    for hit in answer.get("chunks") or answer.get("results") or answer.get("citations") or []:
        if isinstance(hit, dict):
            title = hit.get("title") or hit.get("documentTitle") or hit.get("itemId")
            lines.append(f"  {hit.get('score', '')} {title}: {short(hit.get('text') or hit.get('snippet') or '', 120)}")
    return "\n".join(lines)
