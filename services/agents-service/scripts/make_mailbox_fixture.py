"""Writes tests/fixtures/mailbox/delta_messages.json: 100 Graph delta items for the mailbox adapter (E6).

82 new disputes, 10 redeliveries of earlier ones (same Message-ID, some without brackets or with the domain in another
case), 5 replies to cases waiting on a person, 3 replies to cases that are mid-run when they arrive (marked
`_fixture.midRun`), plus 2 `@removed` items (a delete and a move out of the folder) that are not counted.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mailbox" / "delta_messages.json"
DOMAIN = "mail.northfield.example"
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


def main() -> None:
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
