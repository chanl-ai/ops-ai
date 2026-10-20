"""OCR of the scanned levy notice (c-233): the mailed scan read through ops_ingest into pages, as an extraction
reads it (ops_extract.pages), with every postcode and amount as printed. Speckle made Tesseract read "M8V 1A5" as
"Mav: 1A5"."""

from __future__ import annotations

from pathlib import Path

import pytest

from ops_extract.pages import pages_of
from ops_ingest.models import ParsingSettings
from ops_ingest.parsers import parse
from ops_ingest.parsers.ocr import OcrUnavailableError, TesseractEngine

# The levy scan the mailbox demo sends; documents-service reads it the way the Extract from file step asks.
SCAN = (
    Path(__file__).resolve().parents[2] / "agents-service" / "tests" / "fixtures" / "mailbox" / "levy_notice_scan.pdf"
)


def test_every_postcode_and_amount_on_the_scan_reads_as_printed() -> None:
    try:
        TesseractEngine()
    except OcrUnavailableError as e:
        pytest.skip(str(e))
    pages = pages_of(parse(SCAN.read_bytes(), filename=SCAN.name, parsing=ParsingSettings(ocr=True)))
    text = "\n".join(pages.texts.values())
    printed = ["B3J 1A1", "M8V 1A5", "R3B 2K7", "12,400.00", "3,250.00", "890.50"]
    assert [p for p in printed if p not in text] == [], text
