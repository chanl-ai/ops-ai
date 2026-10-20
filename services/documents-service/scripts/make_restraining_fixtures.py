"""Writes the synthetic restraining notices under tests/fixtures/restraining from notices.json (c-248), the tax levies
under tests/fixtures/tax_levy from levies.json, and the levy demo's mixed email under tests/fixtures/mail (c-270).

    uv run python scripts/make_restraining_fixtures.py

Text PDFs for every notice and variant; TEST010 as an image-only, degraded page (no text layer); scanned copies of
TEST001 and TEST003 (grey background, skew, speckle, low resolution, no text layer); and expected.json, the value
each field should read in each file, which the tests and the seed read. Rendering is deterministic: reportlab's
invariant mode and a seeded speckle, so a rebuild changes a file only when notices.json changes.
"""

from __future__ import annotations

import base64
import io
import json
import random
import time
import zlib
from pathlib import Path
from typing import Any, cast

import pdfplumber
from PIL import Image, ImageFilter
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

rl_config.invariant = 1

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
HERE = FIXTURES / "restraining"
# Each folder's source file and the family its notices are filed under; the tax levies came for the levy demo (c-270).
DATASETS = (("restraining", "notices.json", "photographed"), ("tax_levy", "levies.json", "tax_levy"))
BANNER = "SYNTHETIC TEST DOCUMENT - NOT A REAL LEVY - NO REAL PERSON OR ACCOUNT"
FOOTER = "Synthetic QA fixture. All names, addresses, identifiers, case numbers and agencies are fictional."
LABEL_FILL = colors.HexColor("#DCE3EA")
BANNER_FILL = colors.HexColor("#FFF3B0")
BANNER_TEXT = colors.HexColor("#8B1A1A")

BODY = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=12)
LABEL = ParagraphStyle("label", parent=BODY, fontName="Helvetica-Bold")
HEADING = ParagraphStyle("heading", parent=BODY, fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, spaceAfter=4)
TITLE = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=18, leading=22, alignment=TA_CENTER)
CASE = ParagraphStyle("case", parent=BODY, fontSize=9, alignment=TA_RIGHT)
BANNER_STYLE = ParagraphStyle(
    "banner", fontName="Helvetica-Bold", fontSize=9, leading=12, alignment=TA_CENTER, textColor=BANNER_TEXT
)

Notice = dict[str, Any]


def banner() -> Table:
    t = Table([[Paragraph(BANNER, BANNER_STYLE)]], colWidths=[7 * inch])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BANNER_FILL), ("TOPPADDING", (0, 0), (-1, -1), 5)]))
    return t


def section(heading: str, rows: list[list[str]]) -> list[Flowable]:
    t = Table(
        [[Paragraph(label, LABEL), Paragraph(value, BODY)] for label, value in rows],
        colWidths=[2.1 * inch, 4.9 * inch],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LABEL_FILL),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#9AA5B1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return [Paragraph(heading, HEADING), t]


def notes(text: str) -> list[Flowable]:
    return [Spacer(1, 8), Paragraph("Form notes", HEADING), Paragraph(text, BODY)]


def footer(c: Canvas, doc: Any) -> None:
    c.saveState()
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#707070"))
    c.drawString(0.75 * inch, 0.5 * inch, FOOTER)
    c.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
    c.restoreState()


def build(story: list[Flowable], title: str) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=LETTER, title=title, leftMargin=0.75 * inch, rightMargin=0.75 * inch, topMargin=0.6 * inch
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def table_notice(n: Notice) -> bytes:
    story: list[Flowable] = [banner(), Spacer(1, 10), Paragraph(n["title"], TITLE)]
    story.append(Paragraph(f"Case reference: {n['caseRef']}", CASE))
    for i, page in enumerate(cast(list[dict[str, Any]], n["pages"])):
        if i:
            story.append(PageBreak())
            story.append(Paragraph(f"{n['title']} - {n['caseRef']} (continued)", CASE))
        for s in page["sections"]:
            story += section(s["heading"], s["rows"])
        story += notes(page["notes"])
    return build(story, n["title"])


def lines_notice(n: Notice) -> bytes:
    """Plain typed lines with no tables or banner bar; `**` marks a bold heading line (TEST010)."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=LETTER)
    c.setTitle(n["title"])
    y = 10 * inch
    for line in cast(list[str], n["lines"]):
        bold = line.startswith("**")
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 13 if bold else 12)
        c.drawString(inch, y, line.removeprefix("**"))
        y -= 0.3 * inch
    c.showPage()
    c.save()
    return buf.getvalue()


def variant_rows(v: Notice) -> dict[str, list[list[str]]]:
    return {
        "Parties": [
            ["Judgment creditor", v["creditor"]],
            ["Judgment debtor", v["debtor_name"]],
            ["Debtor address", v["debtor_address"]],
        ],
        "Judgment": [["Court", v["court"]], ["Amount due", v["amount"]]],
        "Service": [["Date served", v["date_served"]], ["Respond by", v["response_deadline"]]],
        "Counsel": [["Attorney", v["attorney"]], ["Attorney address", v["attorney_address"]]],
        "Garnishee": [["TO", v["garnishee"]], ["Address", v["garnishee_address"]]],
    }


def parties_notice(v: Notice) -> bytes:
    """VAR01-VAR05: one layout, five sections; VAR07 the same sections split over two pages."""
    rows = variant_rows(v)
    story: list[Flowable] = [banner(), Spacer(1, 10), Paragraph("RESTRAINING NOTICE", TITLE)]
    story.append(Paragraph(f"Case reference: {v['caseRef']}", CASE))
    if v.get("layout") == "continued":
        for heading in ("Parties", "Judgment"):
            story += section(heading, rows[heading])
        story += notes("Continued on page 2.")
        story += [PageBreak(), Paragraph(f"RESTRAINING NOTICE - {v['caseRef']} (continued)", CASE)]
        for heading in ("Service", "Counsel", "Garnishee"):
            story += section(f"{heading} (continued)", rows[heading])
    else:
        for heading, r in rows.items():
            story += section(heading, r)
        story += notes("Synthetic layout variant.")
    return build(story, "RESTRAINING NOTICE")


def caption_notice(v: Notice) -> bytes:
    """VAR06: a court caption in two columns (parties left, index number right) above the tables."""
    left = Paragraph(
        f"{v['creditor'].upper()},<br/>Plaintiff,<br/><br/>-against-<br/><br/>{v['debtor_name'].upper()},<br/>"
        "Defendant.",
        BODY,
    )
    right = Paragraph(f"Index No. {v['caseRef']}<br/><br/><b>RESTRAINING NOTICE</b>", BODY)
    caption = Table([[left, right]], colWidths=[4.2 * inch, 2.8 * inch])
    caption.setStyle(
        TableStyle([("LINEAFTER", (0, 0), (0, 0), 0.8, colors.black), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    )
    rows = variant_rows(v)
    story: list[Flowable] = [banner(), Spacer(1, 10), Paragraph(v["court"].upper(), TITLE), Spacer(1, 8), caption]
    story += section(
        "To the judgment debtor",
        [["Address", v["debtor_address"]], ["Amount due", v["amount"]], *rows["Service"]],
    )
    story += section("Attorney for the judgment creditor", rows["Counsel"])
    story += section("Garnishee", rows["Garnishee"])
    story += notes("Synthetic layout variant.")
    return build(story, "RESTRAINING NOTICE")


def scanned(pdf: bytes, *, seed: int, dpi: int, angle: float, speckle: int) -> bytes:
    """Each page rasterised and degraded (grey paper, skew, blur, speckle) into an image-only PDF."""
    rng = random.Random(seed)
    pages: list[Image.Image] = []
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        rendered = [page.to_image(resolution=dpi).original.convert("L") for page in doc.pages]
    paper = [int(v * 0.86 + 12) for v in range(256)]  # paper about 231 grey, ink stays dark
    for page_image in rendered:
        img = page_image.point(paper)  # pyright: ignore[reportUnknownMemberType]
        img = img.rotate(angle, expand=True, fillcolor=231, resample=Image.Resampling.BICUBIC)
        img = img.filter(ImageFilter.GaussianBlur(0.5))
        px = img.load()
        assert px is not None
        w, h = img.size
        for _ in range(speckle):
            x, y = rng.randrange(w), rng.randrange(h)
            px[x, y] = rng.choice((40, 90, 255))
        pages.append(img)
    out = io.BytesIO()
    # A fixed date: Pillow stamps the current time otherwise, and every rebuild would change every scan.
    fixed = time.gmtime(1792281600)  # 2026-10-18
    pages[0].save(
        out, "PDF", resolution=float(dpi), save_all=True, append_images=pages[1:], creationDate=fixed, modDate=fixed
    )
    return out.getvalue()


def variant_expected(v: Notice) -> dict[str, Any]:
    name, _, firm = str(v["attorney"]).partition(" / ")
    return {
        "notice_kind": "Restraining notice",
        "case_no": v["caseRef"],
        "court": v["court"],
        "creditor": v["creditor"],
        "debtor_name": v["debtor_name"],
        "debtor_address": v["debtor_address"],
        "amount": v["amount"],
        "date_served": v["date_served"],
        "response_deadline": v["response_deadline"],
        "attorney_name": name,
        "attorney_firm": firm,
        "attorney_address": v["attorney_address"],
        "garnishee": v["garnishee"],
        "garnishee_address": v["garnishee_address"],
    }


def catalogue(data: dict[str, Any], family: str = "photographed") -> tuple[dict[str, bytes], dict[str, Any]]:
    """Every fixture file and the expected.json entry for each."""
    files: dict[str, bytes] = {}
    expected: dict[str, Any] = {}
    for n in cast(list[Notice], data["notices"]):
        entry = {"edge": n["edge"], "invented": n["invented"], "expected": n["expected"], "family": family}
        entry["pages"] = n.get("pages_of", {})
        if n["layout"] == "lines" and n.get("imageOnly"):
            files[f"{n['id']}.pdf"] = scanned(lines_notice(n), seed=10, dpi=150, angle=0.8, speckle=900)
            entry["imageOnly"] = True
        elif n["layout"] == "lines":
            files[f"{n['id']}.pdf"] = lines_notice(n)
        else:
            files[f"{n['id']}.pdf"] = table_notice(n)
        if "groups" in n:
            entry["groups"] = n["groups"]
        expected[f"{n['id']}.pdf"] = entry
        if n.get("scan"):
            # The photographed set seeds by its number, so a rebuild keeps their scans byte for byte.
            name = str(n["id"])
            seed = int(name.removeprefix("TEST")) if name.startswith("TEST") else zlib.crc32(name.encode()) % 1000
            files[f"{n['id']}_scan.pdf"] = scanned(files[f"{n['id']}.pdf"], seed=seed, dpi=120, angle=1.4, speckle=2500)
            expected[f"{n['id']}_scan.pdf"] = {**entry, "imageOnly": True, "scanOf": f"{n['id']}.pdf"}
    if "variants" not in data:
        return files, expected
    variants = data["variants"]
    shared = {"garnishee": variants["garnishee"], "garnishee_address": variants["garnishee_address"]}
    for given in cast(list[Notice], variants["same"]):
        v = {**given, **shared}
        files[f"{v['id']}.pdf"] = parties_notice(v)
        expected[f"{v['id']}.pdf"] = {
            "family": "parties",
            "invented": ["the whole notice"],
            "expected": variant_expected(v),
        }
    for given in cast(list[Notice], variants["other"]):
        v = {**given, **shared}
        files[f"{v['id']}.pdf"] = caption_notice(v) if v["layout"] == "caption" else parties_notice(v)
        entry = {"family": v["layout"], "invented": ["the whole notice"], "expected": variant_expected(v)}
        if v["layout"] == "continued":
            later = ("date_served", "response_deadline", "attorney_name", "attorney_firm", "attorney_address")
            entry["pages"] = dict.fromkeys((*later, "garnishee", "garnishee_address"), 2)
        expected[f"{v['id']}.pdf"] = entry
    return files, expected


# The levy demo's email (c-270): one message carrying several documents of different kinds, as a Graph message item
# (the mailbox fixtures' form, services/agents-service/scripts/send_levy_email.py sends one through GreenMail).
MIXED_EMAIL = (("restraining", "TEST006.pdf"), ("restraining", "TEST012.pdf"), ("tax_levy", "TAXLEVY01.pdf"))


def mixed_email() -> dict[str, Any]:
    attachments = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": name,
            "contentType": "application/pdf",
            "contentBytes": base64.b64encode((FIXTURES / folder / name).read_bytes()).decode("ascii"),
        }
        for folder, name in MIXED_EMAIL
    ]
    return {
        "id": "AAMkMixed001",
        "internetMessageId": "<levies-2026-10-18-0001@process.example>",
        "subject": "Levies served on the bank: two restraining notices and one tax levy",
        "from": {"emailAddress": {"address": "service@process.example", "name": "Demo Process Services"}},
        "receivedDateTime": "2026-10-18T09:30:00Z",
        "body": {
            "contentType": "text",
            "content": (
                "Please find attached two restraining notices and one notice of tax levy for the customers named in "
                "them. Hold funds as each document directs and confirm receipt."
            ),
        },
        "internetMessageHeaders": [],
        "hasAttachments": True,
        "attachments": attachments,
    }


def main() -> None:
    for folder, source, family in DATASETS:
        here = FIXTURES / folder
        files, expected = catalogue(json.loads((here / source).read_text()), family)
        for name, body in files.items():
            (here / name).write_bytes(body)
        (here / "expected.json").write_text(json.dumps(expected, indent=1, sort_keys=True) + "\n")
        print(f"{len(files)} files and expected.json in {here}")
    mail = FIXTURES / "mail"
    mail.mkdir(exist_ok=True)
    (mail / "mixed_levies.json").write_text(json.dumps(mixed_email(), indent=1) + "\n")
    print(f"mixed_levies.json in {mail}")


if __name__ == "__main__":
    main()
