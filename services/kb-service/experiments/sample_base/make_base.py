"""The sample project base: four made-up projects in four industries, ten documents each, written from one table of
facts per project so every question in questions.json has one known answer. Each project has the three shapes the
design started from: a Word note written with bold lines instead of heading styles, a review PDF whose diagram page
has no text layer (a picture), and a change log. All names, people and numbers are invented.

    uv run --directory services/kb-service python experiments/sample_base/make_base.py [OUT]

Writes the 40 files to OUT (default .run/sample-base). score.py loads them into a knowledge base and asks the
questions. Write-up: docs/services/kb-service/experiments/sample-base.md."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

from docx import Document
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

# One row per project; every sentence below is built from these values.
PROJECTS: list[dict[str, Any]] = [
    {
        "slug": "claims-intake",
        "name": "Claims intake redesign",
        "industry": "insurance",
        "parts": ["Mobile app", "Intake service", "Event queue"],
        "lead": "Dana Whitfield",
        "engineer": "Omar Haddad",
        "analyst": "Lena Okafor",
        "choice": "an event queue between intake and the adjusters",
        "reason": "photo uploads arrive in bursts after storms and the adjusters' system could not keep up",
        "rejected": "a nightly batch file",
        "before": "claims reached adjusters the next morning",
        "after": "claims reach adjusters within five minutes",
        "date": "14 October 2026",
        "metric": "photo upload success rate",
        "threshold": "98 percent",
    },
    {
        "slug": "meter-data",
        "name": "Meter data platform",
        "industry": "utilities",
        "parts": ["Smart meters", "Head-end system", "Billing store"],
        "lead": "Rafael Monteiro",
        "engineer": "Grace Lindqvist",
        "analyst": "Tomas Varga",
        "choice": "fifteen-minute interval reads instead of daily reads",
        "reason": "time-of-use tariffs need the load in each quarter hour",
        "rejected": "estimated profiles from daily totals",
        "before": "bills used one read per day",
        "after": "bills use ninety-six reads per day",
        "date": "3 September 2026",
        "metric": "reads received on time",
        "threshold": "99.5 percent",
    },
    {
        "slug": "sb-lending",
        "name": "Small business lending portal",
        "industry": "banking",
        "parts": ["Applicant portal", "Credit decision engine", "Loan servicing"],
        "lead": "Priya Raman",
        "engineer": "Marcus Bell",
        "analyst": "Yuki Tanaka",
        "choice": "cash-flow underwriting from bank statements",
        "reason": "most applicants are under two years old and have thin credit files",
        "rejected": "bureau scores alone",
        "before": "a decision took nine business days",
        "after": "a decision takes two business days",
        "date": "21 August 2026",
        "metric": "applications decided within two days",
        "threshold": "80 percent",
    },
    {
        "slug": "clinic-scheduling",
        "name": "Clinic scheduling service",
        "industry": "healthcare",
        "parts": ["Patient app", "Scheduling service", "Clinic calendar"],
        "lead": "Hannah Brooks",
        "engineer": "Ade Bankole",
        "analyst": "Sofia Ruiz",
        "choice": "holding a slot for ten minutes while the patient confirms",
        "reason": "two patients were booked into the same slot during busy mornings",
        "rejected": "first come first served with no hold",
        "before": "double bookings happened about twice a week",
        "after": "no double booking has been reported since the change",
        "date": "2 November 2026",
        "metric": "slots booked without a conflict",
        "threshold": "99.9 percent",
    },
]


def _pdf(pages: list[list[str] | Image.Image]) -> bytes:
    """A PDF with one page per entry: lines of text drawn in its text layer, or a picture with no text layer."""
    out = io.BytesIO()
    c = Canvas(out, pagesize=LETTER)
    for page in pages:
        if isinstance(page, Image.Image):
            c.drawImage(ImageReader(page), 50, 250, width=512, height=384)  # pyright: ignore[reportUnknownMemberType]
        else:
            y = 720
            for n, line in enumerate(page):
                c.setFont("Helvetica-Bold" if n == 0 else "Helvetica", 16 if n == 0 else 11)
                c.drawString(72, y, line)
                y -= 30 if n == 0 else 16
        c.showPage()
    c.save()
    return out.getvalue()


def _diagram(parts: list[str]) -> Image.Image:
    """Three labelled boxes joined left to right by arrows, as pixels only."""
    img = Image.new("RGB", (1024, 768), "white")
    d = ImageDraw.Draw(img)
    for i, label in enumerate(parts):
        x = 60 + i * 330
        d.rectangle([x, 300, x + 250, 460], outline="black", width=4)
        d.text((x + 20, 370), label, fill="black", font_size=28)
        if i < len(parts) - 1:
            d.line([x + 250, 380, x + 330, 380], fill="black", width=4)
            d.polygon([(x + 330, 380), (x + 315, 370), (x + 315, 390)], fill="black")
    return img


def _docx_bold(title: str, sections: list[tuple[str, list[str]]]) -> bytes:
    """A Word note written the way people write them: bold lines, no heading styles."""
    doc = Document()
    doc.add_paragraph().add_run(title).bold = True
    for head, paras in sections:
        doc.add_paragraph().add_run(head).bold = True
        for p in paras:
            doc.add_paragraph(p)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _docx_styled(title: str, sections: list[tuple[str, list[str]]], table: list[list[str]] | None = None) -> bytes:
    doc = Document()
    doc.add_heading(title, 0)
    for head, paras in sections:
        doc.add_heading(head, 1)
        for p in paras:
            doc.add_paragraph(p)
    if table:
        t = doc.add_table(rows=len(table), cols=len(table[0]))
        for r, row in enumerate(table):
            for k, cell in enumerate(row):
                t.cell(r, k).text = cell
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def documents(p: dict[str, Any]) -> dict[str, bytes]:
    a, b, c = p["parts"]
    s, n = p["slug"], p["name"]
    return {
        f"{s}-decision-note.docx": _docx_bold(
            f"{n} - decision note",
            [
                ("Decision", [f"We chose {p['choice']}.", f"We chose it because {p['reason']}."]),
                ("What we did not choose", [f"We did not choose {p['rejected']}; it would not fix the cause."]),
                ("Who does what", [f"{p['lead']} leads the project. {p['engineer']} builds the {b}."]),
                ("Open risks", [f"If the {b} is down, the {a} keeps the work and sends it later."]),
            ],
        ),
        f"{s}-architecture-review.pdf": _pdf(
            [
                [
                    f"{n}: architecture review",
                    f"Reviewed on {p['date']} by {p['lead']} and {p['engineer']}.",
                    "The diagram on the next page shows how the parts connect.",
                ],
                _diagram(p["parts"]),
            ]
        ),
        f"{s}-team-roster.pdf": _pdf(
            [
                [
                    f"{n}: team",
                    f"{p['lead']} leads the project and approves releases.",
                    f"{p['engineer']} owns the {b} and is on call for it.",
                    f"{p['analyst']} owns the {p['metric']} report and the weekly numbers.",
                ]
            ]
        ),
        f"{s}-changelog.md": (
            f"# {n} change log\n\n## {p['date']}\n\nBefore this change {p['before']}. Now {p['after']}.\n\n"
            f"## Earlier\n\nThe {c} was moved to its own servers.\n"
        ).encode(),
        f"{s}-runbook.pdf": _pdf(
            [
                [
                    f"{n}: runbook",
                    f"When the {b} stops, check its queue depth first.",
                    f"Work from the {a} waits and is sent again when the {b} is back.",
                    f"Page {p['engineer']} if the {b} is down for more than fifteen minutes.",
                ]
            ]
        ),
        f"{s}-meeting-notes.docx": _docx_styled(
            f"{n} - steering meeting",
            [
                ("Attendees", [f"{p['lead']}, {p['engineer']}, {p['analyst']}."]),
                ("Decisions", [f"The team confirmed {p['choice']}.", f"The {p['metric']} target is {p['threshold']}."]),
            ],
        ),
        f"{s}-release-notes.md": (
            f"# {n} release notes\n\n## Release 2.0\n\n"
            f"Shipped on {p['date']}. {p['after'][0].upper()}{p['after'][1:]}.\n"
        ).encode(),
        f"{s}-glossary.md": (
            f"# {n} glossary\n\n## {a}\n\nWhere the work starts.\n\n## {b}\n\nWhat receives the work from the {a} "
            f"and passes it to the {c}.\n\n## {c}\n\nWhere the work ends up.\n"
        ).encode(),
        f"{s}-risk-register.docx": _docx_styled(
            f"{n} - risk register",
            [("Risks", ["Each risk has one owner."])],
            [
                ["Risk", "Owner"],
                [f"The {b} falls behind at peak", p["engineer"]],
                [f"The {p['metric']} drops", p["analyst"]],
            ],
        ),
        f"{s}-onboarding.pdf": _pdf(
            [
                [
                    f"{n}: onboarding",
                    f"This {p['industry']} project has three parts: the {a}, the {b} and the {c}.",
                    f"Ask {p['lead']} for access on your first day.",
                ]
            ]
        ),
    }


def main(argv: list[str]) -> int:
    out = Path(argv[1] if len(argv) > 1 else ".run/sample-base")
    out.mkdir(parents=True, exist_ok=True)
    made = 0
    for p in PROJECTS:
        for name, data in documents(p).items():
            (out / name).write_bytes(data)
            made += 1
    print(f"sample base: {made} documents in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
