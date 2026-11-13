# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Parsers turn a file's bytes into one `ParsedDocument`, whatever the format. PDFs and scanned images are read by
`ops_ingest.reading`, the one reader of page layouts and OCR, and handed back in the same shape."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Literal

from ops_ingest.models import ParsedDocument, ParsingSettings
from ops_ingest.parsers.docx import DOCX_MIME, parse_docx
from ops_ingest.parsers.html import parse_html
from ops_ingest.parsers.ocr import OcrUnavailableError, WordOcr
from ops_ingest.parsers.pptx import PPTX_MIME, UnreadableDeckError, parse_pptx
from ops_ingest.parsers.spreadsheet import XLSX_MIME, parse_csv, parse_xlsx
from ops_ingest.parsers.text import parse_text

#: Spec 1.9: larger files fail with `too_large`.
MAX_FILE_BYTES = 50 * 1024 * 1024

_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".docx": DOCX_MIME,
    ".xlsx": XLSX_MIME,
    ".pptx": PPTX_MIME,
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class UnsupportedFormatError(ValueError):
    code: Literal["unsupported_format", "legacy_format"] = "unsupported_format"


class LegacyFormatError(UnsupportedFormatError):
    """An old binary Office file or a Keynote deck: no reader here, but a person can re-save it in a format with
    one, so the message says how."""

    code = "legacy_format"


# Old formats by extension and by type, each with the format to re-save it as.
_LEGACY_EXTENSIONS = {".ppt": ".pptx", ".pps": ".pptx", ".key": ".pptx", ".xls": ".xlsx", ".doc": ".docx"}
_LEGACY_MIMES = {
    "application/vnd.ms-powerpoint": ".pptx",
    "application/vnd.apple.keynote": ".pptx",
    "application/x-iwork-keynote-sffkey": ".pptx",
    "application/vnd.ms-excel": ".xlsx",
    "application/msword": ".docx",
}


def _refuse_legacy(filename: str, mime: str | None) -> None:
    save_as = _LEGACY_MIMES.get(mime or "") or _LEGACY_EXTENSIONS.get(PurePosixPath(filename).suffix.lower())
    if save_as:
        raise LegacyFormatError(
            f"{filename} is in an older format that cannot be read. Save it as {save_as} and upload it again."
        )


class TooLargeError(ValueError):
    code = "too_large"


def detect_mime(filename: str, mime_type: str | None = None) -> str:
    if mime_type and mime_type != "application/octet-stream":
        given = mime_type.split(";")[0].strip().lower()
        _refuse_legacy(filename, given)
        return given
    mime = _BY_EXTENSION.get(PurePosixPath(filename).suffix.lower())
    if mime is None:
        _refuse_legacy(filename, None)
        raise UnsupportedFormatError(f"No parser for {filename}")
    return mime


def parse(
    data: bytes,
    *,
    filename: str,
    mime_type: str | None = None,
    parsing: ParsingSettings | None = None,
    clean: bool = False,
    fields: dict[str, str] | None = None,
    ocr_engine: WordOcr | None = None,
    mark: bool = False,
) -> ParsedDocument:
    """Parse a file. `clean` is the `clean` ingestion strategy: page furniture is removed from HTML. `mark` keeps
    HTML furniture and marks it on each block instead, for the shared reading."""
    if len(data) > MAX_FILE_BYTES:
        raise TooLargeError(f"{filename} is {len(data)} bytes; the limit is {MAX_FILE_BYTES}")
    parsing = parsing or ParsingSettings()
    mime = detect_mime(filename, mime_type)
    match mime:
        case "application/pdf" | "image/png" | "image/jpeg" | "image/tiff":
            return _read(data, filename=filename, mime=mime, parsing=parsing, fields=fields, ocr_engine=ocr_engine)
        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return parse_docx(data, filename=filename, parsing=parsing, fields=fields)
        case "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return parse_xlsx(data, filename=filename, parsing=parsing, fields=fields)
        case "application/vnd.openxmlformats-officedocument.presentationml.presentation":
            return parse_pptx(data, filename=filename, parsing=parsing, fields=fields)
        case "text/csv":
            return parse_csv(data, filename=filename, parsing=parsing, fields=fields)
        case "text/html" | "application/xhtml+xml":
            return parse_html(data, filename=filename, clean=clean, parsing=parsing, fields=fields, mark=mark)
        case "text/plain" | "text/markdown":
            return parse_text(data, filename=filename, mime_type=mime, parsing=parsing, fields=fields)
        case _:
            raise UnsupportedFormatError(f"No parser for {mime}")


def _read(
    data: bytes,
    *,
    filename: str,
    mime: str,
    parsing: ParsingSettings,
    fields: dict[str, str] | None,
    ocr_engine: WordOcr | None,
) -> ParsedDocument:
    # Imported here: the reader reads other formats through `parse`, so it imports this module.
    from ops_ingest.reading import ReadingError, ReadingSettings, read, to_parsed_document  # noqa: PLC0415

    settings = ReadingSettings(ocr="auto" if parsing.ocr else "off")
    try:
        reading = read(data, filename=filename, mime_type=mime, settings=settings, ocr_engine=ocr_engine)
    except ReadingError as e:
        if e.code == "ocr_unavailable":
            raise OcrUnavailableError(str(e)) from e
        raise
    return to_parsed_document(reading, fields=fields, keep_tables=parsing.tables)


__all__ = [
    "MAX_FILE_BYTES",
    "LegacyFormatError",
    "OcrUnavailableError",
    "TooLargeError",
    "UnreadableDeckError",
    "UnsupportedFormatError",
    "detect_mime",
    "parse",
    "parse_csv",
    "parse_docx",
    "parse_html",
    "parse_pptx",
    "parse_text",
    "parse_xlsx",
]
