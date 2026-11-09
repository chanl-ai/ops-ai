# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import io
import struct
import zlib

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
    MAX_RENDER_PIXELS,
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


@pytest.mark.parametrize("name", ["procedures.docx", "fees.xlsx", "help.html"])
def test_reading_splits_the_same_as_the_parser(name: str) -> None:
    """Section paths, paragraph breaks and tables of the formats read by their parsers survive the trip through a
    reading, with no page numbers invented for formats that have no pages."""
    data = fixture_bytes(name)
    assert to_parsed_document(read(data, filename=name, settings=OFF)) == parse(data, filename=name)


def test_pdf_splits_into_the_sections_the_parser_gave() -> None:
    """The section paths, paragraph breaks, table and pages policy.pdf split into before PDFs moved onto the reader."""
    doc = to_parsed_document(read(fixture_bytes("policy.pdf"), filename="policy.pdf", settings=OFF))
    shape = [
        (s.heading_path, s.page, [(b.kind, b.text if b.kind == "paragraph" else b.headers, b.page) for b in s.blocks])
        for s in doc.sections
    ]
    assert shape == [
        (["Card Fees Policy"], 1, []),
        (
            ["1 Annual fees"],
            1,
            [
                (
                    "paragraph",
                    "Annual fees are charged on the account opening date and on each anniversary. A fee is refunded "
                    "in full when the card is closed within 30 days of the charge.",
                    1,
                ),
                ("table", ["Card", "Annual fee", "Foreign transaction fee"], 1),
            ],
        ),
        (
            ["2 Late payment"],
            2,
            [
                (
                    "paragraph",
                    "A late payment fee of $25 applies when the minimum payment is not received by the due date. The "
                    "fee is waived once in any twelve-month period on request.",
                    2,
                )
            ],
        ),
    ]
    assert doc.tables[0].caption == "Table 1 Annual fees by card"


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


def _pdf(objects: list[bytes]) -> bytes:
    """A PDF from numbered object bodies (object 1 is the catalogue), with a correct cross-reference table."""
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def test_form_field_tree_with_a_cycle_is_read_once() -> None:
    """A widget whose Kids and Parent point back at each other: reading must end, with the field named once."""
    data = _pdf(
        [
            b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [4 0 R] >> >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Annots [5 0 R] >>",
            b"<< /T (applicant) /Kids [5 0 R] /Parent 5 0 R >>",
            b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (name) /V (Ana Ruiz) /Rect [100 700 300 716]"
            b" /Parent 4 0 R /Kids [5 0 R 4 0 R] >>",
        ]
    )
    reading = read(data, filename="cycle.pdf", settings=OFF)
    assert [(f.name, f.value) for f in reading.form_fields] == [("applicant.name", "Ana Ruiz")]


def _bomb_png(side: int) -> bytes:
    """A PNG whose header claims `side` x `side` one-bit pixels: a few hundred KB that decode to gigabytes."""

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    pack = zlib.compressobj(9)
    row = b"\0" * (1 + side // 8)
    rows = row * 1000
    data = b"".join(pack.compress(rows) for _ in range(side // 1000)) + pack.flush()
    header = struct.pack(">IIBBBBB", side, side, 1, 0, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", data) + chunk(b"IEND", b"")


def test_decompression_bomb_image_is_refused_before_decoding() -> None:
    reading = read(_bomb_png(40_000), filename="bomb.png", settings=AUTO, ocr_engine=NoOcr())
    page = reading.pages[0]
    assert page.source == "none"
    assert page.unread_reason is not None and "too large" in page.unread_reason


def test_huge_pdf_page_is_drawn_at_a_bounded_size() -> None:
    out = io.BytesIO()
    canvas = Canvas(out, pagesize=(2880, 2880))  # 40 inches square: 64 million pixels at the OCR resolution
    canvas.showPage()
    canvas.save()
    sizes: list[int] = []

    class Measure:
        def image_to_words(self, image: object) -> list[OcrWord]:
            assert isinstance(image, Image.Image)
            sizes.append(image.width * image.height)
            return []

    read(out.getvalue(), filename="poster.pdf", settings=AUTO, ocr_engine=Measure())
    assert sizes and sizes[0] <= MAX_RENDER_PIXELS


def test_corrupt_image_fails_its_page_with_a_reason() -> None:
    whole = fixture_bytes("scan.png")
    reading = read(whole[: len(whole) // 2], filename="cut.png", settings=AUTO, ocr_engine=NoOcr())
    page = reading.pages[0]
    assert page.source == "none"
    assert page.unread_reason is not None and "could not be decoded" in page.unread_reason
