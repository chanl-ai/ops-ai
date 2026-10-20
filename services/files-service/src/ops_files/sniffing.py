# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""What the stored bytes are, from their first bytes (puremagic, pure Python, so no system libmagic on the VM).

The declared type, the stored Content-Type and the name all come from the sender, so none of them decides what a file
is. Completion reads the first `SNIFF_BYTES` and proves a type from them; the purpose's allowed types are checked
against that type (`check_type`), and the file is recorded and served as it. The sender's type and name only choose
among the types the bytes allow: an 8 KB head shows a zip container but not whether it is a docx, an xlsx or a plain
zip, so `report.docx` is a docx while `report.pdf` with the same bytes is still a zip.

Text has no signature: bytes with no signature and no control characters are text, typed by the declared type or the
name when either is a text type, else text/plain. Binary bytes with no known signature are refused, so a renamed
executable is neither a PDF nor text.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import puremagic

from ops_files.service import TypeNotAllowedError

SNIFF_BYTES = 8192

# Types whose bytes carry no magic number; a signature found in them means the bytes are something else.
TEXT_TYPES = frozenset(
    {
        "text/plain",
        "text/csv",
        "text/markdown",
        "text/html",
        "text/xml",
        "application/json",
        "application/xml",
        "application/x-ndjson",
        "application/yaml",
    }
)
TEXT_BY_EXTENSION = {
    "txt": "text/plain",
    "csv": "text/csv",
    "md": "text/markdown",
    "html": "text/html",
    "htm": "text/html",
    "xml": "application/xml",
    "json": "application/json",
    "ndjson": "application/x-ndjson",
    "yaml": "application/yaml",
    "yml": "application/yaml",
}
# Control characters other than tab, newline, form feed and carriage return; text holds none of them.
_CONTROL = frozenset(range(32)) - {9, 10, 12, 13} | {127}


@dataclass(frozen=True)
class Proven:
    """The type the bytes prove, and the extensions (lowercase, no dot) a purpose's allowed types are matched with."""

    mime: str
    extensions: frozenset[str]
    signed: bool


def candidates(head: bytes) -> list[tuple[str, str]]:
    """(MIME type, extension) pairs puremagic finds in `head`, most confident first; empty when nothing matches. A
    match with no MIME type takes the one its extension names."""
    if not head:
        return []
    try:
        matches: list[Any] = puremagic.magic_string(head)  # pyright: ignore[reportUnknownMemberType]
    except puremagic.PureError:
        return []
    found: list[tuple[float, str, str]] = []
    for m in matches:
        ext = str(m.extension).lstrip(".").lower()
        mime = str(m.mime_type) or (mimetypes.guess_type(f"x.{ext}")[0] or "" if ext else "")
        if mime:
            found.append((-float(m.confidence), mime, ext))
    return list(dict.fromkeys((mime, ext) for _, mime, ext in sorted(found)))


def prove(declared: str, name: str, head: bytes) -> Proven:
    """The type `head` proves for a file sent as `declared` under `name`. Raises `TypeNotAllowedError` for binary
    bytes with no known signature."""
    by_name = PurePosixPath(name).suffix.lstrip(".").lower()
    found = candidates(head)
    if found:
        allowed = list(dict.fromkeys(mime for mime, _ in found))
        named = next((mime for mime, ext in found if ext and ext == by_name), None)
        if named is None and by_name:
            named = next((m for m in allowed if f".{by_name}" in mimetypes.guess_all_extensions(m)), None)
        mime = declared if declared in allowed else named or allowed[0]
        return Proven(mime, _extensions(mime, found), signed=True)
    if not _is_text(head):
        raise TypeNotAllowedError("the bytes match no file type files-service recognises")
    mime = declared if declared in TEXT_TYPES else TEXT_BY_EXTENSION.get(by_name, "text/plain")
    return Proven(mime, _extensions(mime, []), signed=False)


def _is_text(head: bytes) -> bool:
    return not any(b in _CONTROL for b in head)


def _extensions(mime: str, found: list[tuple[str, str]]) -> frozenset[str]:
    exts = {ext for m, ext in found if m == mime and ext}
    exts |= {e.lstrip(".") for e in mimetypes.guess_all_extensions(mime)}
    exts |= {ext for ext, m in TEXT_BY_EXTENSION.items() if m == mime}
    return frozenset(exts)
