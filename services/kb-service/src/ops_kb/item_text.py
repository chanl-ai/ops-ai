# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""An item's text for the document view: documents-service's reading of the item's file, after the source's cleaning,
grouped into sections by its titles and headings, each paragraph and table keeping its place on the page so the view
can highlight it on the original and select it from there. Built from the reading alone; the item's pieces are not
read, since a piece keeps only its page."""

from __future__ import annotations

from collections.abc import Callable

from ops_kb.source_settings import Cleaning
from ops_service_kit import narrow
from ops_service_kit.http import Json, JsonList
from ops_service_kit.narrow import json_list, json_object

# Sent when there is nothing to show beside the original.
NO_FILE = "This document has no file, so only what was indexed can be shown."
NOT_READ_YET = "The file is still being read; its text appears here when the reading ends."
NO_READING = "The file's reading could not be had just now; try again in a minute."


def dropped_by(cleaning: Cleaning, pages: list[Json]) -> Callable[[Json], bool]:
    """The cleaning rule as a test on a block: page furniture when the source drops it, and anything outside the main
    element when the source keeps only the main content and the file has one."""
    blocks = [json_object(b) for p in pages for b in json_list(p.get("blocks"))]
    has_main = cleaning.main_content and any(b.get("main") for b in blocks)

    def dropped(b: Json) -> bool:
        if cleaning.furniture and b.get("furniture"):
            return True
        return has_main and not b.get("main") and b.get("kind") != "title"

    return dropped


def _box(page: int, raw: object) -> Json | None:
    values = [float(v) for v in json_list(raw) if isinstance(v, int | float)]
    if len(values) != 4:
        return None
    x0, top, x1, bottom = values
    return {"page": page, "x": x0, "y": top, "w": x1 - x0, "h": bottom - top}


def _boxes(page: int | None, block: Json) -> JsonList:
    """One box per line of a paragraph when its lines have them, else the block's own box; none without a page."""
    if page is None:
        return []
    lines = [b for line in json_list(block.get("lines")) if (b := _box(page, json_object(line).get("box")))]
    if lines and block.get("kind") == "paragraph":
        return [*lines]
    whole = _box(page, block.get("box"))
    return [whole] if whole else []


def _notes(pages: list[Json]) -> list[str]:
    """Unread pages in plain words, runs of pages with the same reason said once, then OCR pages whose picture was
    not described, with why."""
    runs: list[tuple[int, int, str]] = []
    for p in pages:
        if p.get("source") != "none":
            continue
        number, reason = narrow.field(p, "number", int, 0), str(p.get("unreadReason") or "it could not be read")
        if runs and runs[-1][2] == reason and runs[-1][1] == number - 1:
            runs[-1] = (runs[-1][0], number, reason)
        else:
            runs.append((number, number, reason))
    unread = [
        f"Page {a} was not read. {why}" if a == b else f"Pages {a} to {b} were not read. {why}" for a, b, why in runs
    ]
    # A picture that could not be described on a page OCR read keeps the OCR words; the reason is a warning there.
    kept = [
        f"Page {narrow.field(p, 'number', int, 0)} has only the words OCR read. {w}"
        for p in pages
        if p.get("source") == "ocr"
        for w in (str(x) for x in json_list(p.get("warnings")))
        if w.startswith("Not described")
    ]
    return [*unread, *kept]


def item_text(
    item_id: str,
    file_id: str | None,
    mime: str | None,
    answer: Json | None,
    cleaning: Cleaning,
    *,
    page: int | None = None,
) -> Json:
    """The `ItemText` reply for an item whose file's reading answered `answer` (None: no file, or no answer now). A
    paged file answers one page's sections at a time (`page`, clamped to the file's pages; the first when left out),
    with headings carried from the pages before it; a file without pages answers all of its sections."""
    head: Json = {"itemId": item_id, "fileId": file_id, "mimeType": mime, "readerVersion": None, "page": None}
    empty: Json = {**head, "paged": False, "pages": [], "sections": []}
    if file_id is None:
        return {**empty, "status": "none", "notes": [NO_FILE]}
    if answer is None:
        return {**empty, "status": "none", "notes": [NO_READING]}
    if answer.get("status") != "done":
        return {**empty, "status": "reading", "notes": [NOT_READ_YET]}
    pages = [json_object(p) for p in json_list(answer.get("pages"))]
    paged = bool(json_object(answer.get("facts")).get("paged", True))
    dropped = dropped_by(cleaning, pages)
    sections: JsonList = []
    stack: list[tuple[int, str]] = []
    current: Json | None = None
    for p in pages:
        number = narrow.field(p, "number", int, 0)
        at = number if paged else None
        for b in (json_object(x) for x in json_list(p.get("blocks"))):
            if dropped(b):
                continue
            kind, text = b.get("kind"), str(b.get("text") or "")
            if kind in ("title", "heading"):
                level = narrow.field(b, "level", int, 1)
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, " ".join(text.split())))
                current = None
                continue
            if current is None:
                current = {
                    "id": f"s{len(sections) + 1}",
                    "headingPath": [t for _, t in stack],
                    "page": at,
                    "blocks": [],
                }
                sections.append(current)
            json_list(current["blocks"]).append(
                {
                    "id": str(b.get("id") or f"p{number}.b{len(json_list(current['blocks']))}"),
                    "kind": "table" if kind == "table" else "paragraph",
                    "text": text,
                    "page": at,
                    "readBy": str(b.get("readBy") or "text"),
                    "boxes": _boxes(at, b),
                }
            )
    out_pages: JsonList = [
        {
            "number": narrow.field(p, "number", int, 0),
            "readBy": str(p.get("source") or "text"),
            "unreadReason": p.get("unreadReason"),
            "warnings": [str(w) for w in json_list(p.get("warnings"))],
        }
        for p in pages
    ]
    shown: int | None = None
    if paged and pages:
        shown = min(max(page or 1, 1), len(pages))
        kept: JsonList = []
        for sec in (json_object(x) for x in sections):
            on = [b for b in json_list(sec.get("blocks")) if json_object(b).get("page") == shown]
            if on:
                kept.append({**sec, "blocks": on})
        sections = kept
    return {
        **head,
        "readerVersion": answer.get("readerVersion"),
        "status": "done",
        "paged": paged,
        "page": shown,
        "pages": out_pages,
        "sections": sections,
        "notes": [*_notes(pages)],
    }
