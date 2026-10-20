"""A field's boxes on the page (c-252), by failure mode: a labelled quote lighting up the label instead of the value; a
quote the model made up, or cites on another page, getting a box; a quote over two lines drawn as one box across the
gap; a value in a table cell, quoted from a row the page text joins with " | ", not found or not naming its cell."""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate, Table

from ops_extract.boxes import locate, with_boxes
from ops_extract.layout import build_layout, page_text

WIDTH, HEIGHT = LETTER


def notice() -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 11)
    c.drawString(72, HEIGHT - 100, "Case reference: SYN-TL-2026-0101")
    c.drawString(72, HEIGHT - 140, "Release: this levy is released when the amount due")
    c.drawString(72, HEIGHT - 154, "is paid in full.")
    c.showPage()
    c.drawString(72, HEIGHT - 100, "Page two text")
    c.save()
    return buf.getvalue()


def test_a_labelled_quote_boxes_the_value_where_it_is_printed() -> None:
    layout = build_layout(notice(), filename="n.pdf")
    found = locate(layout, 1, "Case reference: SYN-TL-2026-0101", "SYN-TL-2026-0101")
    assert found is not None and len(found["boxes"]) == 1, found
    box = found["boxes"][0]
    label_end = (72 + Canvas(io.BytesIO()).stringWidth("Case reference: ", "Helvetica", 11)) / WIDTH
    assert box["page"] == 1 and abs(box["x"] - label_end) < 0.01, (box, label_end)
    assert abs(box["y"] - (100 - 11) / HEIGHT) < 0.01 and 0 < box["h"] < 0.03, box
    assert found["blocks"] and all(b.startswith("p1.") for b in found["blocks"]), found


def test_an_invented_or_misplaced_quote_gets_no_box() -> None:
    layout = build_layout(notice(), filename="n.pdf")
    assert locate(layout, 1, "Case reference: SYN-TL-2026-9999", "SYN-TL-2026-9999") is None
    assert locate(layout, 2, "Case reference: SYN-TL-2026-0101", "SYN-TL-2026-0101") is None


def test_a_quote_over_two_lines_is_a_box_per_line() -> None:
    layout = build_layout(notice(), filename="n.pdf")
    quote = "this levy is released when the amount due\nis paid in full."
    found = locate(layout, 1, quote, quote)
    assert found is not None and [b["page"] for b in found["boxes"]] == [1, 1], found
    first, second = found["boxes"]
    assert second["y"] > first["y"] + first["h"] * 0.5 and second["w"] < first["w"], found


def test_a_value_in_a_table_row_names_its_cell() -> None:
    rows = [["Name", "Address", "SSN last four"], ["Marcus Bell", "12 Harbour Street", "4471"]]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER).build([Table(rows, style=[("GRID", (0, 0), (-1, -1), 0.5, "black")])])
    layout = build_layout(buf.getvalue(), filename="r.pdf")
    assert "Marcus Bell | 12 Harbour Street | 4471" in page_text(layout).texts[1]
    found = locate(layout, 1, "Marcus Bell | 12 Harbour Street | 4471", "4471")
    assert found is not None and len(found["blocks"]) == 1 and found["blocks"][0].endswith(".r1.c2"), found


def test_with_boxes_places_each_found_field_and_leaves_the_rest() -> None:
    layout = build_layout(notice(), filename="n.pdf")
    case = {"extractedValue": "SYN-TL-2026-0101", "citation": {"page": 1, "quote": "SYN-TL-2026-0101"}}
    empty = {"extractedValue": None, "citation": None}
    out = with_boxes({"fields": {"case_no": case, "ein": empty}}, layout)
    assert out["fields"]["case_no"]["boxes"] and "boxes" not in out["fields"]["ein"], out


def test_a_date_is_boxed_from_its_printed_text_not_its_normalised_value() -> None:
    """A date normalised to 2026-10-02 is not printed; its box comes from what was printed, without the label."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica", 10)
    c.drawString(340, HEIGHT - 100, "Invoice date")
    c.drawString(440, HEIGHT - 100, "10/02/2026")
    c.save()
    layout = build_layout(buf.getvalue(), filename="d.pdf")
    field = {
        "value": "2026-10-02",
        "extractedValue": "10/02/2026",
        "citation": {"page": 1, "quote": "Invoice date\n10/02/2026"},
    }
    out = with_boxes({"fields": {"invoice_date": field}}, layout)
    [box] = out["fields"]["invoice_date"]["boxes"]
    assert abs(box["x"] - 440 / WIDTH) < 0.01, box
