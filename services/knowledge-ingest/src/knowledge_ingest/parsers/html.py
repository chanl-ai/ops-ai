# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""HTML pages. With `clean`, navigation, cookie banners, footers and other page furniture are removed.

Boilerplate is matched on whole class and id tokens (`site-nav` → `site`, `nav`). Substring matching
removes real content: `ad` is a substring of `header`, `download`, `lead` and `shadow`, so an article
with `class="lead"` would vanish.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from knowledge_ingest.models import ParsedDocument, ParsingSettings, SourceMetadata
from knowledge_ingest.parsers.builder import DocumentBuilder
from knowledge_ingest.parsers.text import decode

# Never content, removed whether or not `clean` is on.
_NON_CONTENT_TAGS = ("script", "style", "noscript", "template", "svg", "iframe", "object", "embed")
# Page furniture, removed with `clean`.
_FURNITURE_TAGS = ("nav", "aside", "footer", "form", "button", "dialog")
_FURNITURE_ROLES = {"navigation", "banner", "contentinfo", "complementary", "search", "dialog"}
_FURNITURE_TOKENS = {
    "nav",
    "navbar",
    "navigation",
    "menu",
    "breadcrumb",
    "breadcrumbs",
    "footer",
    "sidebar",
    "cookie",
    "cookies",
    "consent",
    "gdpr",
    "banner",
    "social",
    "share",
    "sharing",
    "advert",
    "advertisement",
    "ad",
    "ads",
    "popup",
    "modal",
    "subscribe",
    "newsletter",
    "skip",
    "toolbar",
}
_TOKEN_SPLIT = re.compile(r"[\s\-_]+")
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_BLOCK_TEXT = {"p", "li", "pre", "blockquote", "dt", "dd", "figcaption", "address"}


def _tokens(tag: Tag) -> set[str]:
    values: list[str] = []
    classes = tag.get("class")
    if isinstance(classes, list):
        values.extend(str(c) for c in classes)
    elif isinstance(classes, str):
        values.append(classes)
    tag_id = tag.get("id")
    if isinstance(tag_id, str):
        values.append(tag_id)
    return {t.lower() for v in values for t in _TOKEN_SPLIT.split(v) if t}


def _is_furniture(tag: Tag) -> bool:
    if tag.name in _FURNITURE_TAGS:
        return True
    # A page-level <header> is furniture; an <header> inside an article holds the article's title.
    if tag.name == "header" and tag.find_parent(["main", "article"]) is None:
        return True
    role = tag.get("role")
    if isinstance(role, str) and role.lower() in _FURNITURE_ROLES:
        return True
    return bool(_tokens(tag) & _FURNITURE_TOKENS)


def _text(tag: Tag) -> str:
    return " ".join(tag.get_text(" ", strip=True).split())


def _remove(tags: list[Tag]) -> int:
    removed = 0
    for tag in tags:
        if tag.decomposed:
            continue
        removed += len(_text(tag))
        tag.decompose()
    return removed


def _table(tag: Tag, builder: DocumentBuilder, keep: bool) -> None:
    rows: list[list[str]] = []
    headers: list[str] = []
    for tr in tag.find_all("tr"):
        cells = tr.find_all(["th", "td"])
        values = [_text(c) for c in cells]
        if not headers and cells and all(c.name == "th" for c in cells):
            headers = values
        else:
            rows.append(values)
    if not headers and rows:
        headers, rows = rows[0], rows[1:]
    caption_tag = tag.find("caption")
    caption = _text(caption_tag) if caption_tag else None
    builder.table(headers, rows, caption=caption, keep_as_table=keep)


def _walk(node: Tag, builder: DocumentBuilder, keep_tables: bool) -> None:
    loose: list[str] = []

    def flush() -> None:
        if loose:
            builder.paragraph(" ".join(loose))
            loose.clear()

    for child in node.children:
        if isinstance(child, NavigableString):
            text = " ".join(str(child).split())
            if text:
                loose.append(text)
            continue
        if not isinstance(child, Tag):
            continue
        if child.name in _HEADINGS:
            flush()
            builder.heading(_text(child), _HEADINGS[child.name])
        elif child.name == "table":
            flush()
            _table(child, builder, keep_tables)
        elif child.name in _BLOCK_TEXT:
            flush()
            builder.paragraph(_text(child))
        elif child.name in ("ul", "ol", "dl", "div", "section", "article", "main", "header", "body", "figure"):
            flush()
            _walk(child, builder, keep_tables)
        else:
            text = _text(child)
            if text:
                loose.append(text)
    flush()


def parse_html(
    data: bytes,
    *,
    filename: str,
    clean: bool = True,
    parsing: ParsingSettings | None = None,
    fields: dict[str, str] | None = None,
) -> ParsedDocument:
    parsing = parsing or ParsingSettings()
    soup = BeautifulSoup(decode(data), "html.parser")
    builder = DocumentBuilder()

    title_tag = soup.find("title")
    title = _text(title_tag) if title_tag else None

    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()

    root: Tag = soup.body or soup
    if clean:
        removed = _remove([t for t in root.find_all(True) if _is_furniture(t)])
        main = root.find("main") or root.find("article")
        if isinstance(main, Tag):
            outside = len(_text(root)) - len(_text(main))
            removed += max(0, outside)
            root = main
        builder.removed_chars = removed

    _walk(root, builder, parsing.tables)
    source = SourceMetadata(
        filename=filename, mime_type="text/html", size_bytes=len(data), title=title, fields=fields or {}
    )
    return builder.build(title=title, source=source)
