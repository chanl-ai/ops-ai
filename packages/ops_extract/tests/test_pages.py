"""Page text (c-260): a title or a heading, which ops_ingest keeps apart from the blocks under it, left out of the page
text, so the model never sees it and a true quote from it scores 0."""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table

from ops_extract.checks import ground
from ops_extract.pages import pages_of
from ops_ingest.models import ParsingSettings
from ops_ingest.parsers import parse

TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, leading=22)
BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=12)
HEADING = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=12, leading=14)


def notice() -> bytes:
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=LETTER).build(
        [
            Paragraph("RESTRAINING NOTICE", TITLE),
            Paragraph("Case reference: SYN-2026-0012", BODY),
            Spacer(1, 12),
            Paragraph("Case caption", HEADING),
            Table([["Court", "Supreme Test Court"], ["Judgment debtor", "Sage Prototype"]]),
            Paragraph("The debtor named above is restrained from transferring property.", BODY),
            Table([["SSN", "000-12-0012"]]),
        ]
    )
    return buf.getvalue()


def test_a_title_and_a_heading_reach_the_page_and_ground_a_quote() -> None:
    pages = pages_of(parse(notice(), filename="notice.pdf", parsing=ParsingSettings()))
    page = pages.texts[1]
    assert "RESTRAINING NOTICE" in page and "Case caption" in page, page
    assert ground("RESTRAINING NOTICE", 1, pages.texts) == 1.0
