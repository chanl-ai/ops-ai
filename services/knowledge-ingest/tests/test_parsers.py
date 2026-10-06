# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import sys

import pytest

from knowledge_ingest.models import Paragraph, ParsingSettings
from knowledge_ingest.parsers import MAX_FILE_BYTES, OcrUnavailableError, TooLargeError, parse
from tests.conftest import fixture_bytes, requires_tesseract


def test_scanned_page_without_ocr_is_reported() -> None:
    doc = parse(fixture_bytes("scanned.pdf"), filename="scanned.pdf", parsing=ParsingSettings(ocr=False))
    assert doc.plain_text() == ""
    assert doc.pages_without_text == [1]
    assert any("Page 1" in w and "OCR is off" in w for w in doc.warnings)


@requires_tesseract
def test_scanned_page_is_read_with_ocr() -> None:
    doc = parse(fixture_bytes("scanned.pdf"), filename="scanned.pdf", parsing=ParsingSettings(ocr=True))
    assert doc.ocr_pages == [1]
    text = doc.plain_text().upper()
    assert "LATE PAYMENT FEE" in text
    assert "25" in text


def test_ocr_requested_but_missing_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(OcrUnavailableError):
        parse(fixture_bytes("scanned.pdf"), filename="scanned.pdf", parsing=ParsingSettings(ocr=True))


def test_pdf_table_keeps_headers_and_caption() -> None:
    doc = parse(fixture_bytes("policy.pdf"), filename="policy.pdf")
    [table] = doc.tables
    assert table.headers == ["Card", "Annual fee", "Foreign transaction fee"]
    assert table.rows[1] == ["Gold", "$95", "2%"]
    assert table.caption == "Table 1 Annual fees by card"


def test_pdf_table_cells_not_repeated_as_prose() -> None:
    doc = parse(fixture_bytes("policy.pdf"), filename="policy.pdf")
    prose = " ".join(b.text for s in doc.sections for b in s.blocks if isinstance(b, Paragraph))
    assert "Platinum" not in prose
    assert "Foreign transaction fee" not in prose


def test_pdf_sections_carry_page_numbers() -> None:
    doc = parse(fixture_bytes("policy.pdf"), filename="policy.pdf")
    pages = {s.heading_path[-1]: s.page for s in doc.sections if s.blocks}
    assert pages == {"1 Annual fees": 1, "2 Late payment": 2}
    assert doc.source.page_count == 2


def test_docx_heading_path_and_table_placement() -> None:
    doc = parse(fixture_bytes("procedures.docx"), filename="procedures.docx")
    by_path = {tuple(s.heading_path): s for s in doc.sections}
    ack = by_path[("1 Receiving a complaint", "1.1 Acknowledgement")]
    assert [t.headers for t in ack.tables] == [["Channel", "Acknowledge within"]]
    assert ("2 Escalation",) in by_path
    assert doc.title == "Complaint Handling Procedure"


def test_xlsx_headers_and_cell_values() -> None:
    doc = parse(fixture_bytes("fees.xlsx"), filename="fees.xlsx")
    [table] = doc.tables
    assert table.headers == ["Product", "Balance band", "Monthly fee", "Internal note"]
    assert table.rows[0] == ["Everyday Account", "<= $250,000", "5", "legacy pricing"]
    assert table.rows[3][2] == "2.5"
    assert table.sheet == "Fees"


def test_html_clean_removes_page_furniture() -> None:
    doc = parse(fixture_bytes("help.html"), filename="help.html", clean=True)
    text = doc.plain_text()
    for furniture in ("Accounts", "cookies", "Travel insurance", "All rights reserved", "analytics", "Share on"):
        assert furniture not in text
    assert "freeze the card in the app" in text
    assert doc.removed_chars > 0


def test_html_clean_keeps_content_with_lookalike_classes() -> None:
    doc = parse(fixture_bytes("help.html"), filename="help.html", clean=True)
    assert "Report a lost card straight away" in doc.plain_text()


def test_oversized_file_is_refused() -> None:
    with pytest.raises(TooLargeError) as err:
        parse(b"x" * (MAX_FILE_BYTES + 1), filename="big.txt")
    assert err.value.code == "too_large"
