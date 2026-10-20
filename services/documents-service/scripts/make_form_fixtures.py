"""Writes two non-levy fixture families (c-255) under tests/fixtures/invoice and tests/fixtures/bank_statement, so
classify, templates and boxes are proven on more than one kind of document.

    uv run python scripts/make_form_fixtures.py

Each family has six text PDFs printed from one master form (layout A), two from another form (layout B), a scan of a
layout A page shifted a few millimetres and one skewed by two degrees (a template reads both; a value OCR misreads on
the skewed one fails its checks and goes to review), and expected.json, the value each field should read in each
file. Rendering is deterministic: reportlab's invariant mode and fixed scan offsets, so a rebuild changes a file only
when this script changes."""

from __future__ import annotations

import io
import json
import time
from pathlib import Path
from typing import Any

import pdfplumber
from PIL import Image
from reportlab import rl_config
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen.canvas import Canvas

rl_config.invariant = 1

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
BANNER = "SYNTHETIC TEST DOCUMENT - NO REAL PERSON, COMPANY OR ACCOUNT"
W, H = LETTER
SCAN_DPI = 200
# A fixed date: Pillow stamps the current time otherwise, and every rebuild would change every scan.
FIXED = time.gmtime(1792281600)  # 2026-10-18

INVOICES: list[dict[str, str]] = [
    {
        "invoice_no": "INV-30117",
        "vendor": "Harbour Supplies Ltd",
        "bill_to": "Northfield Bank Facilities",
        "invoice_date": "10/02/2026",
        "due_date": "11/01/2026",
        "tax": "$162.50",
        "total": "$1,412.50",
    },
    {
        "invoice_no": "INV-30142",
        "vendor": "Northern Paper Co",
        "bill_to": "Northfield Bank Branch 12",
        "invoice_date": "10/05/2026",
        "due_date": "11/04/2026",
        "tax": "$41.39",
        "total": "$359.79",
    },
    {
        "invoice_no": "INV-30188",
        "vendor": "Bluewater Logistics",
        "bill_to": "Northfield Bank Operations",
        "invoice_date": "10/07/2026",
        "due_date": "11/06/2026",
        "tax": "$910.54",
        "total": "$7,914.69",
    },
    {
        "invoice_no": "INV-30203",
        "vendor": "Kestrel Office Goods",
        "bill_to": "Northfield Bank Legal",
        "invoice_date": "10/09/2026",
        "due_date": "11/08/2026",
        "tax": "$13.00",
        "total": "$112.99",
    },
    {
        "invoice_no": "INV-30251",
        "vendor": "Pinecrest Catering",
        "bill_to": "Northfield Bank Events",
        "invoice_date": "10/12/2026",
        "due_date": "11/11/2026",
        "tax": "$313.30",
        "total": "$2,723.30",
    },
    {
        "invoice_no": "INV-30290",
        "vendor": "Ridgeway Print Shop",
        "bill_to": "Northfield Bank Marketing",
        "invoice_date": "10/14/2026",
        "due_date": "11/13/2026",
        "tax": "$7.31",
        "total": "$63.51",
    },
    {
        "invoice_no": "INV-30311",
        "vendor": "Summit Cleaning Services",
        "bill_to": "Northfield Bank Facilities",
        "invoice_date": "10/16/2026",
        "due_date": "11/15/2026",
        "tax": "$97.50",
        "total": "$847.50",
    },
    {
        "invoice_no": "INV-30344",
        "vendor": "Granite IT Partners",
        "bill_to": "Northfield Bank Technology",
        "invoice_date": "10/19/2026",
        "due_date": "11/18/2026",
        "tax": "$650.00",
        "total": "$5,650.00",
    },
]
INVOICES_B: list[dict[str, str]] = [
    {
        "invoice_no": "TX-8812",
        "vendor": "Cedar Lane Furniture",
        "bill_to": "Northfield Bank Branch 4",
        "invoice_date": "10/03/2026",
        "due_date": "10/31/2026",
        "tax": "$228.00",
        "total": "$2,128.00",
    },
    {
        "invoice_no": "TX-8840",
        "vendor": "Atlas Courier Group",
        "bill_to": "Northfield Bank Mailroom",
        "invoice_date": "10/11/2026",
        "due_date": "11/10/2026",
        "tax": "$18.20",
        "total": "$158.20",
    },
]
STATEMENTS: list[dict[str, str]] = [
    {
        "account_holder": "Morgan Example",
        "account_last4": "4417",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$3,210.44",
        "closing_balance": "$2,987.10",
    },
    {
        "account_holder": "Quinn Caption",
        "account_last4": "8820",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$12,004.00",
        "closing_balance": "$13,450.75",
    },
    {
        "account_holder": "Blair Sidebar",
        "account_last4": "0391",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$88.12",
        "closing_balance": "$412.60",
    },
    {
        "account_holder": "Cameron Fixture",
        "account_last4": "5562",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$54,300.00",
        "closing_balance": "$51,875.25",
    },
    {
        "account_holder": "Leslie Sample",
        "account_last4": "7708",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$1,000.00",
        "closing_balance": "$1,642.33",
    },
    {
        "account_holder": "Avery Specimen",
        "account_last4": "2245",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$7,415.90",
        "closing_balance": "$6,999.99",
    },
    {
        "account_holder": "Jordan Mockup",
        "account_last4": "9134",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$2,500.00",
        "closing_balance": "$2,731.48",
    },
    {
        "account_holder": "Riley Template",
        "account_last4": "6083",
        "period_start": "09/01/2026",
        "period_end": "09/30/2026",
        "opening_balance": "$640.25",
        "closing_balance": "$505.00",
    },
]
STATEMENTS_B: list[dict[str, str]] = [
    {
        "account_holder": "Casey Draft",
        "account_last4": "3371",
        "period_start": "08/16/2026",
        "period_end": "09/15/2026",
        "opening_balance": "$9,120.00",
        "closing_balance": "$8,804.12",
    },
    {
        "account_holder": "Drew Placeholder",
        "account_last4": "1158",
        "period_start": "08/16/2026",
        "period_end": "09/15/2026",
        "opening_balance": "$310.40",
        "closing_balance": "$1,295.40",
    },
]

INVOICE_MISPRINT = {
    "invoice_no": "INV-30399", "vendor": "Westfield Hardware", "bill_to": "Northfield Bank Facilities",
    "invoice_date": "10/21/2026", "due_date": "11/20/2026", "tax": "$26.00", "total": "$226.00",
}  # fmt: skip
STATEMENT_MISPRINT = {
    "account_holder": "Sam Misprint", "account_last4": "4602", "period_start": "09/01/2026",
    "period_end": "09/30/2026", "opening_balance": "$410.00", "closing_balance": "$388.15",
}  # fmt: skip


def _page(draw: Any) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, H - 28, BANNER)
    draw(c)
    c.setFont("Helvetica", 7)
    c.drawString(72, 30, "Synthetic QA fixture. All names, companies and account numbers are fictional.")
    c.save()
    return buf.getvalue()


def _rows(
    c: Canvas, x_label: float, x_value: float, top: float, rows: list[tuple[str, str]], *, step: float = 22
) -> None:
    for i, (label, value) in enumerate(rows):
        y = top - step * i
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x_label, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(x_value, y, value)


def invoice_a(v: dict[str, str]) -> bytes:
    def draw(c: Canvas) -> None:
        c.setFont("Helvetica-Bold", 20)
        c.drawString(72, H - 80, "INVOICE")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(72, H - 108, v["vendor"])
        c.setFont("Helvetica", 9)
        c.drawString(72, H - 122, "Accounts receivable, 210 Commerce Way")
        _rows(
            c,
            340,
            440,
            H - 80,
            [("Invoice number", v["invoice_no"]), ("Invoice date", v["invoice_date"]), ("Due date", v["due_date"])],
        )
        _rows(c, 72, 160, H - 170, [("Bill to", v["bill_to"])])
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, H - 220, "Description")
        c.drawString(460, H - 220, "Amount")
        c.setFont("Helvetica", 10)
        c.drawString(72, H - 240, "Services and goods as agreed")
        _rows(c, 340, 460, H - 300, [("Tax", v["tax"]), ("Total due", v["total"])])

    return _page(draw)


def invoice_b(v: dict[str, str]) -> bytes:
    def draw(c: Canvas) -> None:
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(W / 2, H - 70, f"{v['vendor']} - TAX INVOICE")
        _rows(
            c,
            72,
            180,
            H - 120,
            [
                ("Inv #", v["invoice_no"]),
                ("Issued", v["invoice_date"]),
                ("Pay by", v["due_date"]),
                ("Customer", v["bill_to"]),
            ],
            step=18,
        )
        _rows(c, 72, 180, H - 260, [("GST/Tax", v["tax"]), ("Amount payable", v["total"])], step=18)

    return _page(draw)


def statement_a(v: dict[str, str]) -> bytes:
    def draw(c: Canvas) -> None:
        c.setFont("Helvetica-Bold", 18)
        c.drawString(72, H - 80, "Harbourview Savings Bank")
        c.setFont("Helvetica", 11)
        c.drawString(72, H - 98, "Account statement")
        _rows(
            c,
            72,
            220,
            H - 140,
            [
                ("Account holder", v["account_holder"]),
                ("Account number", f"XXXX-XXXX-{v['account_last4']}"),
                ("Statement period", f"{v['period_start']} to {v['period_end']}"),
            ],
        )
        _rows(
            c, 340, 470, H - 140, [("Opening balance", v["opening_balance"]), ("Closing balance", v["closing_balance"])]
        )
        c.setFont("Helvetica-Bold", 10)
        c.drawString(72, H - 230, "Date")
        c.drawString(160, H - 230, "Description")
        c.drawString(470, H - 230, "Amount")
        c.setFont("Helvetica", 10)
        c.drawString(72, H - 248, v["period_start"])
        c.drawString(160, H - 248, "Opening balance carried forward")

    return _page(draw)


def statement_b(v: dict[str, str]) -> bytes:
    def draw(c: Canvas) -> None:
        c.setFont("Helvetica-Bold", 15)
        c.drawRightString(W - 72, H - 70, "LAKESIDE CREDIT UNION")
        c.setFont("Helvetica", 10)
        c.drawRightString(W - 72, H - 86, "Member statement")
        _rows(
            c,
            72,
            200,
            H - 130,
            [
                ("Member", v["account_holder"]),
                ("Acct ending", v["account_last4"]),
                ("From", v["period_start"]),
                ("Through", v["period_end"]),
                ("Beginning balance", v["opening_balance"]),
                ("Ending balance", v["closing_balance"]),
            ],
            step=18,
        )

    return _page(draw)


def scanned(pdf: bytes, *, shift: tuple[int, int], angle: float) -> bytes:
    """The page rasterised into an image-only PDF, moved by `shift` pixels and turned by `angle` degrees."""
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        page = doc.pages[0].to_image(resolution=SCAN_DPI).original.convert("L")
    moved = Image.new("L", page.size, 255)
    moved.paste(page, shift)
    if angle:
        moved = moved.rotate(angle, fillcolor=255, resample=Image.Resampling.BICUBIC)
    out = io.BytesIO()
    moved.save(out, "PDF", resolution=float(SCAN_DPI), creationDate=FIXED, modDate=FIXED)
    return out.getvalue()


# A date printed impossible on one more copy of each master form: the template reads it, the date check rejects it,
# and the field goes to review with no value, never saved as found.
MISPRINTED = "13/45/2026"


def family(
    folder: str,
    a: Any,
    b: Any,
    rows_a: list[dict[str, str]],
    rows_b: list[dict[str, str]],
    *,
    prefix: str,
    misprint: tuple[dict[str, str], str],
) -> None:
    here = FIXTURES / folder
    here.mkdir(parents=True, exist_ok=True)
    expected: dict[str, Any] = {}
    for i, v in enumerate(rows_a[:6], start=1):
        name = f"{prefix}A0{i}.pdf"
        (here / name).write_bytes(a(v))
        expected[name] = {"layout": "A", "expected": v}
    for i, v in enumerate(rows_b, start=1):
        name = f"{prefix}B0{i}.pdf"
        (here / name).write_bytes(b(v))
        expected[name] = {"layout": "B", "expected": v, "edge": "another form: the layout A template misses it"}
    shifted, skewed = rows_a[6], rows_a[7]
    (here / f"{prefix}A07_scan.pdf").write_bytes(scanned(a(shifted), shift=(14, 10), angle=0))
    expected[f"{prefix}A07_scan.pdf"] = {
        "layout": "A",
        "imageOnly": True,
        "expected": shifted,
        "edge": "a scan shifted a few millimetres: the template reads it",
    }
    (here / f"{prefix}A08_scan.pdf").write_bytes(scanned(a(skewed), shift=(0, 0), angle=2.0))
    expected[f"{prefix}A08_scan.pdf"] = {
        "layout": "A",
        "imageOnly": True,
        "expected": skewed,
        "edge": "a scan skewed two degrees: still within the template's tolerance; a value OCR misreads goes to review",
    }
    values, key = misprint
    (here / f"{prefix}A09_misprint.pdf").write_bytes(a({**values, key: MISPRINTED}))
    expected[f"{prefix}A09_misprint.pdf"] = {
        "layout": "A",
        "expected": {**values, key: None},
        "printedInvalid": {key: MISPRINTED},
        "edge": f"{key} printed as {MISPRINTED}: read, rejected as a date, sent to review with no value",
    }
    (here / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")


def main() -> None:
    family("invoice", invoice_a, invoice_b, INVOICES, INVOICES_B, prefix="INV", misprint=(INVOICE_MISPRINT, "due_date"))
    family(
        "bank_statement",
        statement_a,
        statement_b,
        STATEMENTS,
        STATEMENTS_B,
        prefix="STMT",
        misprint=(STATEMENT_MISPRINT, "period_end"),
    )


if __name__ == "__main__":
    main()
