# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""One reading of a file into pages, used by every caller that needs what a file says.

`read` reads a whole file. `open_file` gives the file's facts and reads one page at a time, so a caller can save each
page as it finishes and carry on from the next page after a restart. A reading depends only on the file's bytes, the
`ReadingSettings` and `READER_VERSION`, so a caller can store it under those and use it again for any purpose.

OCR modes: `off` reads text layers only and lists other pages as unread; `auto` OCRs a page with no text layer and the
picture areas of a page where pictures cover at least `MIXED_IMAGE_SHARE` of it; `always` OCRs every page, for files
whose text layer is known to be wrong.
"""

from __future__ import annotations

import shutil
import time
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import PurePosixPath
from typing import Protocol

from ops_ingest.parsers import MAX_FILE_BYTES, UnsupportedFormatError, detect_mime
from ops_ingest.reading.images import IMAGE_MIMES, LOW_CONFIDENCE, Engines, ImageFile, WordOcr
from ops_ingest.reading.models import (
    READER_VERSION,
    Block,
    Cell,
    FileFacts,
    FormField,
    Line,
    OcrMode,
    OcrQuality,
    Page,
    Reading,
    ReadingError,
    ReadingSettings,
    UnreadPage,
    Word,
    page_text,
)
from ops_ingest.reading.parsed import FORM_FIELDS_HEADING, ParsedFile, to_parsed_document
from ops_ingest.reading.pdf import MAX_PAGES, MIXED_IMAGE_SHARE, PdfFile


class FileReader(Protocol):
    facts: FileFacts

    def page(self, number: int) -> Page: ...

    def close(self) -> None: ...


def _mime(filename: str, mime_type: str | None) -> str:
    if mime_type and mime_type != "application/octet-stream":
        return mime_type.split(";")[0].strip().lower()
    image = IMAGE_MIMES.get(PurePosixPath(filename).suffix.lower())
    if image:
        return image
    try:
        return detect_mime(filename, mime_type)
    except UnsupportedFormatError as exc:
        raise ReadingError("unsupported_format", str(exc)) from exc


@contextmanager
def open_file(
    data: bytes,
    *,
    filename: str,
    mime_type: str | None = None,
    settings: ReadingSettings | None = None,
    ocr_engine: WordOcr | None = None,
) -> Generator[FileReader]:
    """The file opened for reading. Raises `ReadingError` for a file that cannot be read at all: too large, too many
    pages, a format with no reader, or bytes that are not the format they claim. OCR that is needed but not installed
    raises `ReadingError("ocr_unavailable")` from the page that needs it."""
    if len(data) > MAX_FILE_BYTES:
        raise ReadingError("too_large", f"{filename} is {len(data)} bytes; the limit is {MAX_FILE_BYTES}")
    settings = settings or ReadingSettings()
    engines = Engines(settings, ocr_engine)
    mime = _mime(filename, mime_type)
    reader: FileReader
    if mime == "application/pdf":
        reader = PdfFile(data, filename=filename, settings=settings, engines=engines)
    elif mime.startswith("image/"):
        reader = ImageFile(data, filename=filename, mime_type=mime, settings=settings, engines=engines)
    else:
        try:
            reader = ParsedFile(data, filename=filename, mime_type=mime)
        except UnsupportedFormatError as exc:
            raise ReadingError("unsupported_format", str(exc)) from exc
    try:
        yield reader
    finally:
        reader.close()


def read(
    data: bytes,
    *,
    filename: str,
    mime_type: str | None = None,
    settings: ReadingSettings | None = None,
    ocr_engine: WordOcr | None = None,
) -> Reading:
    """The whole file read, every page in order."""
    settings = settings or ReadingSettings()
    started = time.perf_counter()
    with open_file(data, filename=filename, mime_type=mime_type, settings=settings, ocr_engine=ocr_engine) as reader:
        pages = [reader.page(n) for n in range(1, reader.facts.page_count + 1)]
        facts = reader.facts
    return Reading(
        settings=settings, facts=facts, pages=pages, duration_ms=round((time.perf_counter() - started) * 1000)
    )


def ocr_installed() -> bool:
    """Whether the Tesseract binary is on PATH, for a service's health report: without it every scanned page fails."""
    return shutil.which("tesseract") is not None


__all__ = [
    "FORM_FIELDS_HEADING",
    "LOW_CONFIDENCE",
    "MAX_PAGES",
    "MIXED_IMAGE_SHARE",
    "READER_VERSION",
    "Block",
    "Cell",
    "FileFacts",
    "FileReader",
    "FormField",
    "Line",
    "OcrMode",
    "OcrQuality",
    "Page",
    "Reading",
    "ReadingError",
    "ReadingSettings",
    "UnreadPage",
    "Word",
    "WordOcr",
    "ocr_installed",
    "open_file",
    "page_text",
    "read",
    "to_parsed_document",
]
