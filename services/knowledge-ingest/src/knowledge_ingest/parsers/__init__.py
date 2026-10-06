# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Parsers turn a file's bytes into one `ParsedDocument`, whatever the format."""

from __future__ import annotations

from pathlib import PurePosixPath

from knowledge_ingest.models import ParsedDocument, ParsingSettings
from knowledge_ingest.parsers.docx import DOCX_MIME, parse_docx
from knowledge_ingest.parsers.html import parse_html
from knowledge_ingest.parsers.ocr import OcrEngine, OcrUnavailableError
from knowledge_ingest.parsers.pdf import parse_pdf
from knowledge_ingest.parsers.spreadsheet import XLSX_MIME, parse_csv, parse_xlsx
from knowledge_ingest.parsers.text import parse_text

#: Spec 1.9: larger files fail with `too_large`.
MAX_FILE_BYTES = 50 * 1024 * 1024

_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": DOCX_MIME,
    ".xlsx": XLSX_MIME,
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
}


class UnsupportedFormatError(ValueError):
    code = "unsupported_format"


class TooLargeError(ValueError):
    code = "too_large"


def detect_mime(filename: str, mime_type: str | None = None) -> str:
    if mime_type and mime_type != "application/octet-stream":
        return mime_type.split(";")[0].strip().lower()
    mime = _BY_EXTENSION.get(PurePosixPath(filename).suffix.lower())
    if mime is None:
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
    ocr_engine: OcrEngine | None = None,
) -> ParsedDocument:
    """Parse a file. `clean` is the `clean` ingestion strategy: page furniture is removed from HTML."""
    if len(data) > MAX_FILE_BYTES:
        raise TooLargeError(f"{filename} is {len(data)} bytes; the limit is {MAX_FILE_BYTES}")
    parsing = parsing or ParsingSettings()
    mime = detect_mime(filename, mime_type)
    match mime:
        case "application/pdf":
            return parse_pdf(data, filename=filename, parsing=parsing, fields=fields, ocr_engine=ocr_engine)
        case "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            return parse_docx(data, filename=filename, parsing=parsing, fields=fields)
        case "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
            return parse_xlsx(data, filename=filename, parsing=parsing, fields=fields)
        case "text/csv":
            return parse_csv(data, filename=filename, parsing=parsing, fields=fields)
        case "text/html" | "application/xhtml+xml":
            return parse_html(data, filename=filename, clean=clean, parsing=parsing, fields=fields)
        case "text/plain" | "text/markdown":
            return parse_text(data, filename=filename, mime_type=mime, parsing=parsing, fields=fields)
        case _:
            raise UnsupportedFormatError(f"No parser for {mime}")


__all__ = [
    "MAX_FILE_BYTES",
    "OcrEngine",
    "OcrUnavailableError",
    "TooLargeError",
    "UnsupportedFormatError",
    "detect_mime",
    "parse",
    "parse_csv",
    "parse_docx",
    "parse_html",
    "parse_pdf",
    "parse_text",
    "parse_xlsx",
]
