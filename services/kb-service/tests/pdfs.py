"""Text PDFs with headings across pages, a scanned page with words only in its picture, and a blank scan with no text
even by OCR, built in the test."""

from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate
from reportlab.platypus import Image as PdfImage


def policy_pdf(title: str, sections: list[tuple[str, str]]) -> bytes:
    """One section per page: a Heading1 and its paragraph."""
    styles = getSampleStyleSheet()
    out = io.BytesIO()
    story: list[Flowable] = [Paragraph(title, styles["Title"])]
    for n, (heading, body) in enumerate(sections):
        if n:
            story.append(PageBreak())
        story += [Paragraph(heading, styles["Heading1"]), Paragraph(body, styles["BodyText"])]
    SimpleDocTemplate(out, pagesize=A4, title=title).build(story)
    return out.getvalue()


def partly_scanned_pdf() -> bytes:
    """A text page, then a page that is only an image, as a scan stapled to a typed policy."""
    styles = getSampleStyleSheet()
    png = io.BytesIO()
    Image.new("RGB", (300, 200), "white").save(png, "PNG")
    png.seek(0)
    out = io.BytesIO()
    story: list[Flowable] = [
        Paragraph("Overdraft Policy", styles["Title"]),
        Paragraph("1 Limits", styles["Heading1"]),
        Paragraph("An arranged overdraft is capped at 1,000 dollars for a new account.", styles["BodyText"]),
        PageBreak(),
        PdfImage(png, width=300, height=200),
    ]
    SimpleDocTemplate(out, pagesize=A4, title="Overdraft Policy").build(story)
    return out.getvalue()


def scanned_pdf() -> bytes:
    """A page that is only a picture of printed words: readable by OCR alone."""
    image = Image.new("L", (1240, 1754), 255)
    ImageDraw.Draw(image).text((100, 200), "LATE PAYMENT FEE 25 DOLLARS", fill=0, font=ImageFont.load_default(size=56))
    out = io.BytesIO()
    image.save(out, "PDF", resolution=150.0)
    return out.getvalue()


def blank_scan_pdf() -> bytes:
    """A page that is only a blank picture: no text, even by OCR."""
    out = io.BytesIO()
    Image.new("L", (620, 877), 255).save(out, "PDF", resolution=75.0)
    return out.getvalue()


HARDSHIP = policy_pdf(
    "Mortgage Hardship Policy",
    [
        ("1 Eligibility", "A borrower who lost their job may defer up to three mortgage payments in a year."),
        ("2 Interest", "Deferred interest is capitalised into the loan balance at the end of the deferral."),
    ],
)
RATES = policy_pdf(
    "Rate Sheet",
    [("1 Fixed rates", "The five-year fixed mortgage rate is 4.89 percent for insured borrowers.")],
)
