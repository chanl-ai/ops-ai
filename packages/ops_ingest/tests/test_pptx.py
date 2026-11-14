# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
# python-pptx ships partial stubs: placeholders, chart data and shape text are typed as their base classes, so the
# fixture builders below read as unknown or wrong types though they run as documented.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportArgumentType=false
"""PowerPoint decks through the shared reading, by failure mode: a slide's text, notes, table or chart is lost or
lands on another slide's page; a slide with only a picture fails the file or vanishes, so slide numbers shift."""

from __future__ import annotations

import io

from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.presentation import Presentation as Deck
from pptx.slide import Slide
from pptx.util import Inches

from ops_ingest.reading import ReadingSettings, read

OFF = ReadingSettings(ocr="off")


def _deck(build: object) -> bytes:
    prs = Presentation()
    build(prs)  # type: ignore[operator]
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def _title_slide(prs: Deck, title: str, body: str) -> Slide:
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = title
    slide.placeholders[1].text = body
    return slide


def test_slides_read_in_order_with_notes_tables_and_charts() -> None:
    def build(prs: Deck) -> None:
        first = _title_slide(prs, "Q3 lending review", "Approvals rose 12 percent")
        first.notes_slide.notes_text_frame.text = "Mention the Denver branch first"
        rows = first.shapes.add_table(2, 2, Inches(1), Inches(5), Inches(4), Inches(1)).table
        for (r, c), text in {(0, 0): "Product", (0, 1): "Rate", (1, 0): "Term loan", (1, 1): "6.25"}.items():
            rows.cell(r, c).text = text
        second = prs.slides.add_slide(prs.slide_layouts[5])
        second.shapes.title.text = "Pipeline by region"
        data = CategoryChartData()
        data.categories = ["East", "West"]
        data.add_series("Applications", (40, 55))
        chart = second.shapes.add_chart(
            XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(2), Inches(6), Inches(4), data
        ).chart
        chart.has_title = True
        chart.chart_title.text_frame.text = "Applications per region"

    reading = read(_deck(build), filename="review.pptx", settings=OFF)

    assert [p.number for p in reading.pages] == [1, 2] and reading.facts.paged
    first, second = reading.pages[0].text, reading.pages[1].text
    assert first.index("Q3 lending review") < first.index("Approvals rose 12 percent") < first.index("Term loan")
    assert "Mention the Denver branch first" in first and "Notes" in first
    assert "Pipeline" not in first
    assert "Pipeline by region" in second and "Applications per region" in second
    table = next(b for b in reading.pages[1].blocks if b.kind == "table")
    assert {"Applications", "East", "55"} <= {c.text for c in table.cells}


def test_a_picture_only_slide_is_an_empty_page_in_its_place() -> None:
    picture = io.BytesIO()
    Image.new("RGB", (40, 40), "navy").save(picture, format="PNG")

    def build(prs: Deck) -> None:
        _title_slide(prs, "Agenda", "Rates and pipeline")
        blank = prs.slides.add_slide(prs.slide_layouts[6])
        picture.seek(0)
        blank.shapes.add_picture(picture, Inches(1), Inches(1))
        _title_slide(prs, "Next steps", "Send the term sheet")

    reading = read(_deck(build), filename="agenda.pptx", settings=OFF)

    assert [p.number for p in reading.pages] == [1, 2, 3]
    assert reading.pages[1].text == "" and reading.pages[1].blocks == []
    assert "Next steps" in reading.pages[2].text
