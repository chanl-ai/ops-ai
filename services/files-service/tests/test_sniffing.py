# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""The type completion proves from the bytes (c-234): the sender's declared type and name only choose among the types
the bytes allow, and binary bytes with no known signature are refused."""

from __future__ import annotations

import io
import zipfile

import pytest

from ops_files.service import TypeNotAllowedError
from ops_files.sniffing import prove

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
EXE = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx() -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", "<w/>")
    return out.getvalue()


@pytest.mark.parametrize(
    ("declared", "name", "head", "mime"),
    [
        # A mail client that sends a PDF as octet-stream under a bare name.
        ("application/octet-stream", "scan", PDF, "application/pdf"),
        ("application/octet-stream", "debtors.csv", b"name,amount\nBell,3250\n", "text/csv"),
        ("application/octet-stream", "notice.docx", _docx(), DOCX),
        # The sender's type cannot make text into a PDF.
        ("application/pdf", "notice.pdf", b"plain text renamed .pdf", "text/plain"),
    ],
)
def test_the_bytes_decide_the_type(declared: str, name: str, head: bytes, mime: str) -> None:
    assert prove(declared, name, head).mime == mime


def test_a_name_cannot_make_a_zip_a_pdf() -> None:
    proven = prove("application/zip", "notice.pdf", _docx())
    assert "pdf" not in proven.extensions and proven.mime == "application/zip", proven


def test_an_executable_declared_as_a_pdf_is_an_executable() -> None:
    proven = prove("application/pdf", "notice.pdf", EXE)
    assert "exe" in proven.extensions and "pdf" not in proven.extensions, proven


def test_binary_bytes_with_no_known_signature_are_refused() -> None:
    with pytest.raises(TypeNotAllowedError):
        prove("application/pdf", "notice.pdf", b"\x00\x13\x37\x00\xfe\xed\x01\x02 unknown binary")
