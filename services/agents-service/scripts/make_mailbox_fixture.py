"""Writes the mailbox fixtures under tests/fixtures/mailbox.

`delta_messages.json`: 100 Graph delta items for the mailbox adapter (E6): 82 new disputes, 10 redeliveries of earlier
ones (same Message-ID, some without brackets or with the domain in another case), 5 replies to cases waiting on a
person, 3 replies to cases that are mid-run when they arrive (marked `_fixture.midRun`), plus 2 `@removed` items (a
delete and a move out of the folder) that are not counted.

`levy_notice.pdf` and `levy_notice.json` (c-057): one garnishment notice naming three persons, the PDF with a text
layer listing each person's name, address, last four of their SSN, amount, court and case number, and the Graph item
that carries it as a base64 `contentBytes` attachment. Two persons match customers the fake bank seeds
(services/tools-service/scripts/fake_bank/app.py), one matches none.
"""

from __future__ import annotations

import base64
import io
import json
import random
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mailbox"
OUT = FIXTURES / "delta_messages.json"
LEVY_PDF = FIXTURES / "levy_notice.pdf"
LEVY_ITEM = FIXTURES / "levy_notice.json"
# name, address, last four of the SSN, amount, court, case number. The first two are fake-bank customers.
LEVY_PERSONS: list[dict[str, str]] = [
    {
        "name": "Marcus Bell",
        "address": "12 Harbour Street, Halifax NS B3J 1A1",
        "ssn_last4": "4471",
        "amount": "3,250.00",
        "court": "Nova Scotia Supreme Court",
        "case_no": "NS-2026-GN-01187",
    },
    {
        "name": "Priya Natarajan",
        "address": "88 Lakeshore Road, Toronto ON M8V 1A5",
        "ssn_last4": "9032",
        "amount": "12,400.00",
        "court": "Ontario Superior Court of Justice",
        "case_no": "ON-2026-GN-04421",
    },
    {
        "name": "Jordan Whitfield",
        "address": "301 Pine Avenue, Winnipeg MB R3B 2K7",
        "ssn_last4": "1180",
        "amount": "890.50",
        "court": "Manitoba Court of King's Bench",
        "case_no": "MB-2026-GN-00318",
    },
]
DOMAIN = "mail.harborpine.example"
WORDS = [
    "statement",
    "merchant",
    "charge",
    "refund",
    "card",
    "dispute",
    "receipt",
    "amount",
    "posted",
    "pending",
    "order",
    "invoice",
    "reference",
]


def mid(i: int, *, variant: str = "exact") -> str:
    if variant == "bare":
        return f"case-{i:03d}@{DOMAIN}"
    if variant == "upper":
        return f"<case-{i:03d}@{DOMAIN.upper()}>"
    return f"<case-{i:03d}@{DOMAIN}>"


def new_case(i: int, rng: random.Random, *, variant: str = "exact") -> dict[str, Any]:
    attachments = [
        {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": f"evidence-{i:03d}-{n}.txt",
            "contentType": "text/plain",
            "contentBytes": " ".join(f"{rng.choice(WORDS)}{rng.randint(0, 9999)}" for _ in range(60)),
        }
        for n in range(rng.randint(0, 3))
    ]
    return {
        "id": f"AAMk{i:03d}",
        "internetMessageId": mid(i, variant=variant),
        "subject": f"Disputed charge on my card, case {i}",
        "from": {"emailAddress": {"address": f"customer{i:03d}@example.com", "name": f"Customer {i}"}},
        "receivedDateTime": f"2026-10-11T09:{i // 60:02d}:{i % 60:02d}Z",
        "body": {"contentType": "text", "content": f"I do not recognise a charge on my statement (case {i})."},
        "internetMessageHeaders": [],
        "hasAttachments": bool(attachments),
        "attachments": attachments,
    }


def reply(n: int, to_case: int, *, mid_run: bool = False) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": f"AAMkR{n:02d}",
        "internetMessageId": f"<reply-{n:02d}@example.com>",
        "subject": f"Re: Disputed charge on my card, case {to_case}",
        "from": {"emailAddress": {"address": f"customer{to_case:03d}@example.com"}},
        "receivedDateTime": f"2026-10-11T10:00:{n:02d}Z",
        "body": {"contentType": "text", "content": f"Here is more detail for case {to_case}."},
        "internetMessageHeaders": [
            {"name": "In-Reply-To", "value": mid(to_case)},
            {"name": "References", "value": mid(to_case)},
        ],
        "hasAttachments": False,
        "attachments": [],
    }
    if mid_run:
        item["_fixture"] = {"midRun": True}
    return item


def levy_pdf(persons: list[dict[str, str]]) -> bytes:
    """A one-page notice with a text layer: a heading, then one block per person. Text is drawn line by line so a
    text extractor reads each field on its own line."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    c.setTitle("Notice of Garnishment")
    y = 740
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, "NOTICE OF GARNISHMENT - THIRD PARTY (Harbor & Pine Bank)")
    y -= 24
    c.setFont("Helvetica", 10)
    c.drawString(72, y, "The garnishee shall hold funds of each judgment debtor listed below up to the amount shown.")
    y -= 28
    for i, p in enumerate(persons, 1):
        c.setFont("Helvetica-Bold", 11)
        c.drawString(72, y, f"Debtor {i}: {p['name']}")
        y -= 16
        c.setFont("Helvetica", 10)
        for label, key in (
            ("Address", "address"),
            ("SSN (last four)", "ssn_last4"),
            ("Amount", "amount"),
            ("Court", "court"),
            ("Case No", "case_no"),
        ):
            value = f"***-**-{p[key]}" if key == "ssn_last4" else p[key]
            c.drawString(90, y, f"{label}: {value}")
            y -= 14
        y -= 10
    c.showPage()
    c.save()
    return buf.getvalue()


def levy_item(pdf: bytes, persons: list[dict[str, str]]) -> dict[str, Any]:
    names = ", ".join(p["name"] for p in persons)
    return {
        "id": "AAMkLevy001",
        "internetMessageId": "<garnishment-2026-10-15-0147@court.example>",
        "subject": "Notice of garnishment: judgment debtors Marcus Bell, Priya Natarajan, Jordan Whitfield",
        "from": {"emailAddress": {"address": "registry@court.example", "name": "Court Registry"}},
        "receivedDateTime": "2026-10-15T09:14:00Z",
        "body": {
            "contentType": "text",
            "content": (
                f"Please find attached a notice of garnishment naming {names}. Hold the amounts listed in the notice "
                "and confirm to the registry within five business days."
            ),
        },
        "internetMessageHeaders": [],
        "hasAttachments": True,
        "attachments": [
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "notice-of-garnishment.pdf",
                "contentType": "application/pdf",
                "contentBytes": base64.b64encode(pdf).decode("ascii"),
            }
        ],
    }


def write_levy() -> None:
    pdf = levy_pdf(LEVY_PERSONS)
    LEVY_PDF.write_bytes(pdf)
    LEVY_ITEM.write_text(json.dumps(levy_item(pdf, LEVY_PERSONS), indent=1) + "\n")


def main() -> None:
    write_levy()
    rng = random.Random(6)
    items: list[dict[str, Any]] = []
    items += [new_case(i, rng) for i in range(50)]
    items += [
        new_case(i, random.Random(i), variant=v)
        for i, v in zip(range(5), ["exact", "bare", "upper", "exact", "bare"], strict=True)
    ]
    items += [reply(n, 20 + n) for n in range(3)]
    items += [reply(3 + n, 30 + n, mid_run=True) for n in range(2)]
    items += [new_case(i, rng) for i in range(50, 82)]
    items += [
        new_case(i, random.Random(i), variant=v)
        for i, v in zip(range(5, 10), ["upper", "exact", "exact", "bare", "upper"], strict=True)
    ]
    items += [reply(5 + n, 23 + n) for n in range(2)]
    items += [reply(7, 32, mid_run=True)]
    items += [
        {"id": "AAMk900", "@removed": {"reason": "deleted"}},
        {"id": "AAMk901", "@removed": {"reason": "changed"}},
    ]
    assert sum(1 for x in items if "@removed" not in x) == 100
    OUT.write_text(json.dumps(items, indent=1) + "\n")


if __name__ == "__main__":
    main()
