"""Scans straightened before OCR (c-294), by failure mode: a page scanned a few degrees off read with words split or
misread (F1); a page scanned sideways read as noise (F2); a straight, clean page changed (F4). Pages are printed here
and turned as a scanner would."""

from __future__ import annotations

import io

import pdfplumber
import pytest
from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

from ops_ingest.parsers.ocr import OcrUnavailableError, TesseractEngine, skew, straightened

REFERENCES = [f"SYN-2026-{1000 + i}" for i in range(12)]


@pytest.fixture(scope="module")
def engine() -> TesseractEngine:
    try:
        return TesseractEngine()
    except OcrUnavailableError as e:
        pytest.skip(str(e))


@pytest.fixture(scope="module")
def page() -> Image.Image:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 11)
    for i, ref in enumerate(REFERENCES):
        c.drawString(72, 700 - 22 * i, f"Reference {ref} amount due $1,{200 + i}.50 by 11/{10 + i}/2026")
    c.save()
    with pdfplumber.open(io.BytesIO(buf.getvalue())) as pdf:
        return pdf.pages[0].to_image(resolution=200).original.convert("L")


def read(engine: TesseractEngine, image: Image.Image) -> set[str]:
    return {w.text for w in engine.image_to_words(image)}


def test_a_page_scanned_off_straight_reads_every_reference(engine: TesseractEngine, page: Image.Image) -> None:
    turned = page.rotate(4.5, fillcolor=255, resample=Image.Resampling.BICUBIC)
    assert abs(skew(turned) + 4.5) <= 0.25
    assert set(REFERENCES) <= read(engine, turned), sorted(set(REFERENCES) - read(engine, turned))


def test_a_page_scanned_sideways_is_turned_upright(engine: TesseractEngine, page: Image.Image) -> None:
    sideways = page.rotate(90, expand=True, fillcolor=255)
    assert set(REFERENCES) <= read(engine, sideways), sorted(set(REFERENCES) - read(engine, sideways))


def test_a_straight_clean_page_is_left_as_it_is(engine: TesseractEngine, page: Image.Image) -> None:
    assert skew(page) == 0
    prepared = engine.prepared(page)
    assert isinstance(prepared, Image.Image) and prepared.size == page.size
    assert set(REFERENCES) <= read(engine, page)


def test_a_page_a_little_off_is_left_for_tesseract(page: Image.Image) -> None:
    """Turning a page 1 degree off would soften its characters for nothing: Tesseract reads it as scanned."""
    slightly = page.rotate(1.0, fillcolor=255, resample=Image.Resampling.BICUBIC)
    assert straightened(slightly) is slightly


def test_a_word_on_a_sideways_page_is_boxed_where_it_is_printed_on_the_scan(
    engine: TesseractEngine, page: Image.Image
) -> None:
    """Boxes are mapped back through the turn the reader made (F2): read off the upright copy, a box on a sideways scan
    would sit across the wrong part of the page, so a reviewer's highlight would miss the value."""
    upright = {w.text: w.box for w in engine.image_to_words(page) if w.text in REFERENCES}
    sideways = page.rotate(90, expand=True, fillcolor=255)
    found = {w.text: w.box for w in engine.image_to_words(sideways) if w.text in REFERENCES}
    width = page.width
    off: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for ref, (left, top, w, h) in upright.items():
        # A quarter turn counter-clockwise moves (x, y) on the page to (y, width - x) on the sideways scan.
        want = (top, width - (left + w), h, w)
        got = found.get(ref)
        if got is None or any(abs(a - b) > 8 for a, b in zip(want, got, strict=True)):
            off[ref] = (want, got or ())
    assert len(upright) == len(REFERENCES) and not off, off
