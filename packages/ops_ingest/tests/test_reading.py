# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import io

import pytest
from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from ops_ingest.parsers import parse
from ops_ingest.parsers.ocr import OcrUnavailableError, OcrWord
from ops_ingest.reading import (
    FORM_FIELDS_HEADING,
    MAX_PAGES,
    ReadingError,
    ReadingSettings,
    open_file,
    read,
    to_parsed_document,
)
from tests.conftest import fixture_bytes, requires_tesseract

AUTO = ReadingSettings(ocr="auto")
OFF = ReadingSettings(ocr="off")


class FakeOcr:
    """Answers every picture with the given words, boxes given as fractions of the picture it is handed."""

    def __init__(self, words: list[tuple[str, tuple[float, float, float, float], float]]) -> None:
        self.words = words
        self.calls = 0

    def image_to_words(self, image: object) -> list[OcrWord]:
        assert isinstance(image, Image.Image)
        self.calls += 1
        out: list[OcrWord] = []
        for text, (x0, y0, x1, y1), conf in self.words:
            w, h = image.width, image.height
            box = (round(x0 * w), round(y0 * h), round((x1 - x0) * w), round((y1 - y0) * h))
            out.append(OcrWord(text, box, conf, (1, 1, 1)))
        return out


class NoOcr:
    def image_to_words(self, image: object) -> list[OcrWord]:
        raise AssertionError("OCR ran on a page that did not need it")


@requires_tesseract
def test_scanned_pdf_is_read_by_ocr_with_word_confidence() -> None:
    reading = read(fixture_bytes("scanned.pdf"), filename="scanned.pdf", settings=AUTO)
    page = reading.pages[0]
    assert page.source == "ocr"
    assert "LATE PAYMENT FEE" in page.text
    assert page.ocr is not None and 0 < page.ocr.mean <= 1
    assert all(w.confidence < 1.0 for w in page.words)
    assert reading.ocr_pages == [1]


@requires_tesseract
def test_picture_half_of_a_mixed_page_is_read() -> None:
    page = read(fixture_bytes("half_scan.pdf"), filename="half_scan.pdf", settings=AUTO).pages[0]
    assert page.source == "mixed"
    assert page.image_share == pytest.approx(0.25, abs=0.01)
    # The three values printed only in the picture, and the four in the text layer.
    for value in ["+1 415 555 0142", "m.okonkwo@example.org", "2026-02-19", "PL-90385217", "WX-4471-B"]:
        assert value in page.text
    assert {b.read_by for b in page.blocks} == {"text", "ocr"}
    assert page.text.index("PL-90385217") < page.text.index("m.okonkwo@example.org")


def test_small_picture_does_not_start_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_: object, **__: object) -> None:
        raise OcrUnavailableError("tesseract not on PATH")

    monkeypatch.setattr("ops_ingest.reading.images.TesseractEngine", missing)
    page = read(fixture_bytes("small_picture.pdf"), filename="small_picture.pdf", settings=AUTO).pages[0]
    assert page.source == "text"
    assert page.image_share == pytest.approx(0.1, abs=0.01)
    assert "nine to five" in page.text


def test_scan_with_ocr_off_is_listed_unread() -> None:
    reading = read(fixture_bytes("scanned.pdf"), filename="scanned.pdf", settings=OFF, ocr_engine=NoOcr())
    assert reading.pages[0].source == "none"
    assert [(u.page, u.reason) for u in reading.unread] == [(1, "no text layer and OCR is off")]
    parsed = to_parsed_document(reading)
    assert parsed.pages_without_text == [1]


def test_always_ocrs_a_text_page_and_reports_low_confidence() -> None:
    engine = FakeOcr([("Annual", (0.1, 0.1, 0.2, 0.12), 0.9), ("fees", (0.21, 0.1, 0.3, 0.12), 0.5)])
    reading = read(
        fixture_bytes("policy.pdf"), filename="policy.pdf", settings=ReadingSettings(ocr="always"), ocr_engine=engine
    )
    assert engine.calls == 2
    page = reading.pages[0]
    assert page.source == "ocr" and page.text == "Annual fees"
    assert page.ocr is not None and (page.ocr.mean, page.ocr.low_share) == (0.7, 0.5)


def test_text_layer_over_a_scan_is_not_read_twice() -> None:
    """A scanner's own OCR text over a full-page picture: OCR'd words on top of a text-layer word are dropped."""
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=LETTER)
    width, height = LETTER
    canvas.drawImage(ImageReader(Image.new("L", (850, 1100), 255)), 0, 0, width=width, height=height)  # pyright: ignore[reportUnknownMemberType]
    canvas.setFont("Helvetica", 12)
    canvas.drawString(100, height - 100, "Overdraft")
    canvas.showPage()
    canvas.save()
    on_word = ((100 + 10) / width, (100 - 8) / height, (100 + 30) / width, (100 - 2) / height)
    engine = FakeOcr([("Overdraft", on_word, 0.8), ("limit", (0.5, 0.5, 0.6, 0.52), 0.8)])
    page = read(out.getvalue(), filename="layered.pdf", settings=AUTO, ocr_engine=engine).pages[0]
    assert page.source == "mixed"
    assert page.text.split("\n") == ["Overdraft", "limit"]


def test_form_values_are_read_from_the_form_dictionary() -> None:
    reading = read(fixture_bytes("form.pdf"), filename="form.pdf", settings=AUTO, ocr_engine=NoOcr())
    fields = {f.name: (f.value, f.kind) for f in reading.form_fields}
    assert len(fields) == 8
    assert fields["policy_number"] == ("PL-90385217", "text")
    assert fields["consent"] == ("checked", "checkbox")
    assert all(f.page == 1 and f.box is not None for f in reading.form_fields)
    assert "PL-90385217" not in reading.pages[0].text  # the text layer holds only the labels


def test_form_fields_are_searchable_after_splitting() -> None:
    parsed = to_parsed_document(read(fixture_bytes("form.pdf"), filename="form.pdf", settings=OFF))
    section = next(s for s in parsed.sections if s.heading_path == [FORM_FIELDS_HEADING])
    assert "policy_number: PL-90385217" in section.paragraphs[0].text.split("\n")


@requires_tesseract
def test_image_files_are_read_one_page_per_frame() -> None:
    png = read(fixture_bytes("scan.png"), filename="scan.png", settings=AUTO)
    tiff = read(fixture_bytes("scan.tiff"), filename="scan.tiff", settings=AUTO)
    assert [p.source for p in png.pages] == ["ocr"]
    assert "PL-90385217" in png.pages[0].text
    assert [p.source for p in tiff.pages] == ["ocr", "ocr"]
    assert "m.okonkwo@example.org" in tiff.pages[1].text


def test_file_over_the_page_limit_is_refused() -> None:
    out = io.BytesIO()
    canvas = Canvas(out)
    for _ in range(MAX_PAGES + 1):
        canvas.showPage()
    canvas.save()
    with pytest.raises(ReadingError) as caught:
        read(out.getvalue(), filename="long.pdf", settings=OFF)
    assert caught.value.code == "too_many_pages"


def test_ocr_needed_but_missing_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(*_: object, **__: object) -> None:
        raise OcrUnavailableError("tesseract not on PATH")

    monkeypatch.setattr("ops_ingest.reading.images.TesseractEngine", missing)
    with pytest.raises(ReadingError) as caught:
        read(fixture_bytes("scanned.pdf"), filename="scanned.pdf", settings=AUTO)
    assert caught.value.code == "ocr_unavailable"


@pytest.mark.parametrize(
    ("data", "filename", "code"),
    [(b"PK\x03\x04", "slides.pptx", "unsupported_format"), (b"%PDF-1.4 not really", "broken.pdf", "unreadable_file")],
)
def test_file_without_a_reader_fails_with_a_reason(data: bytes, filename: str, code: str) -> None:
    with pytest.raises(ReadingError) as caught:
        read(data, filename=filename, settings=OFF)
    assert caught.value.code == code


@pytest.mark.parametrize("name", ["policy.pdf", "procedures.docx", "fees.xlsx", "help.html"])
def test_reading_splits_the_same_as_the_parser(name: str) -> None:
    """Section paths, paragraph breaks, tables and page numbers survive the switch from parsing to reading."""
    data = fixture_bytes(name)
    assert to_parsed_document(read(data, filename=name, settings=OFF)) == parse(data, filename=name)


def test_page_read_on_its_own_matches_a_whole_read() -> None:
    """After a restart a reading carries on from its next page; heading levels are measured over the whole file, so
    page 2's smaller heading stays level 2 when page 2 is read alone."""
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=LETTER)
    _, height = LETTER
    for size, heading in ((20, "1 Overdrafts"), (14, "1.1 Arranged limits")):
        canvas.setFont("Helvetica", size)
        canvas.drawString(72, height - 72, heading)
        canvas.setFont("Helvetica", 10)
        canvas.drawString(72, height - 110, "An arranged overdraft is agreed before the account goes below zero.")
        canvas.showPage()
    canvas.save()
    data = out.getvalue()
    whole = read(data, filename="levels.pdf", settings=OFF)
    with open_file(data, filename="levels.pdf", settings=OFF) as reader:
        alone = reader.page(2)
    alone.duration_ms = whole.pages[1].duration_ms
    assert alone == whole.pages[1]
    assert (alone.blocks[0].kind, alone.blocks[0].level) == ("heading", 2)
