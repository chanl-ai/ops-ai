"""A file's layout and the text an extraction reads from it (c-247), by failure mode: a table row reaching the model as
one `label | value` line it copies whole into the value, or a wider record split from its row (F4); two columns side
by side merged into one line (F4); OCR boxes left in image pixels, so a highlight lands elsewhere on the page (F3);
an OCR'd field scored by one flat factor whatever Tesseract's confidence (US3); a masked value or a placeholder used
as the value (F6)."""

from __future__ import annotations

import io
import time

from PIL import Image
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate, Table

from ops_extract.checks import score
from ops_extract.layout import OCR_RESOLUTION, build_layout, page_text
from ops_ingest.parsers.ocr import OcrWord

NO_FLOOR = {"file_id": "f", "schema_below": None, "floor": 0.5}


def test_each_table_cell_is_a_line_of_its_own() -> None:
    rows = [["Taxpayer", "Morgan Example"], ["Address", "101 Mockingbird Lane"]]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER).build([Table(rows, style=[("GRID", (0, 0), (-1, -1), 0.5, "black")])])
    text = page_text(build_layout(buf.getvalue(), filename="n.pdf")).texts[1]
    assert "Taxpayer\nMorgan Example\nAddress\n101 Mockingbird Lane" in text and "|" not in text, text


def test_a_wider_row_stays_one_record() -> None:
    rows = [["Name", "Address", "SSN last four"], ["Marcus Bell", "12 Harbour Street", "4471"]]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER).build([Table(rows, style=[("GRID", (0, 0), (-1, -1), 0.5, "black")])])
    text = page_text(build_layout(buf.getvalue(), filename="r.pdf")).texts[1]
    assert "Marcus Bell | 12 Harbour Street | 4471" in text, text


def test_two_columns_on_one_line_stay_apart() -> None:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.drawString(72, 700, "SUMMIT EXAMPLE FINANCE,")
    c.drawString(380, 700, "Index No. SYN-2026-0106")
    c.save()
    lines = page_text(build_layout(buf.getvalue(), filename="c.pdf")).texts[1].splitlines()
    assert lines == ["SUMMIT EXAMPLE FINANCE,", "Index No. SYN-2026-0106"], lines


class _Engine:
    """Tesseract's answer for one word, in the rendered image's pixels."""

    size: tuple[int, int] = (0, 0)

    def image_to_words(self, image: object) -> list[OcrWord]:
        assert isinstance(image, Image.Image)
        self.size = image.size
        return [OcrWord("6789", (850, 1100, 170, 50), 0.62, (1, 1, 1))]


def test_ocr_boxes_are_fractions_of_the_page_and_carry_confidence() -> None:
    scan = io.BytesIO()
    Image.new("L", (850, 1100), 255).save(scan, "PDF", resolution=100.0)
    engine = _Engine()
    layout = build_layout(scan.getvalue(), filename="s.pdf", ocr=True, engine=engine)
    [word] = layout["words"]
    width, height = engine.size
    assert (width, height) == (round(8.5 * OCR_RESOLUTION), round(11 * OCR_RESOLUTION))
    want = [round(850 / width, 4), round(1100 / height, 4), round(1020 / width, 4), round(1150 / height, 4)]
    assert word["box"] == want, word
    pages = page_text(layout)
    assert pages.ocr == {1} and pages.confidence == {1: {"6789": 0.62}}


def test_an_ocr_field_scores_at_its_words_confidence() -> None:
    field = {"key": "ssn_last4", "type": "text"}
    answer = {"value": "6789", "quote": "6789", "page": 1}
    pages = {1: "SSN XXX-XX-6789\n6789"}
    kept = score(field, answer, pages, {1}, **NO_FLOOR, word_confidence={1: {"6789": 0.62}})  # pyright: ignore[reportArgumentType]
    flat = score(field, answer, pages, {1}, **NO_FLOOR)  # pyright: ignore[reportArgumentType]
    assert (kept["confidence"], flat["confidence"]) == (0.62, 0.7)


def test_a_masked_value_and_a_placeholder_are_emptied_and_marked() -> None:
    pages = {1: "SSN ***-**-4321\nAddress Not supplied on this form"}
    ssn = {"key": "ssn_full", "type": "text", "pattern": r"\d{3}-\d{2}-\d{4}"}
    address = {"key": "debtor_address", "type": "text", "emptyWhen": ["Not supplied on this form"]}
    said = "Not supplied on this form"
    masked = score(ssn, {"value": "***-**-4321", "quote": "***-**-4321", "page": 1}, pages, set(), **NO_FLOOR)  # pyright: ignore[reportArgumentType]
    placeholder = score(address, {"value": said, "quote": said, "page": 1}, pages, set(), **NO_FLOOR)  # pyright: ignore[reportArgumentType]
    assert (masked["value"], masked["needsReview"], masked["rejected"]) == (None, True, "pattern"), masked
    assert (placeholder["value"], placeholder["rejected"], placeholder["extractedValue"]) == (None, "emptyWhen", said)


def test_a_pattern_that_backtracks_badly_gives_up_in_time() -> None:
    """A team's pattern meets the model's text: on `re`, (a|aa)+$ against 40 a's and a ! takes minutes (c-247)."""
    field = {"key": "ref", "type": "text", "pattern": r"(a|aa)+$"}
    said = "a" * 40 + "!"
    started = time.monotonic()
    scored = score(field, {"value": said, "quote": said, "page": 1}, {1: said}, set(), **NO_FLOOR)  # pyright: ignore[reportArgumentType]
    assert time.monotonic() - started < 1 and (scored["value"], scored["rejected"]) == (None, "pattern"), scored
