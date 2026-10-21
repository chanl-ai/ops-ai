"""Emails the levy notice (tests/fixtures/mailbox/levy_notice.json, with its PDF) to the levy mailbox on GreenMail, so
the workflow worker reads it over IMAP like any team mailbox and levy_intake opens a levy_case per debtor (c-229).

    uv run python scripts/send_levy_email.py
    uv run python scripts/send_levy_email.py --key-suffix ref-2   # a new message, not a redelivery
    uv run python scripts/send_levy_email.py --fixture ../documents-service/tests/fixtures/mail/mixed_levies.json \
        --mailbox levies@harborpine.test --key-suffix run-2   # the mixed levies email, as a new message

`levy@harborpine.example` (seed/mailboxes.json) is an IMAP mailbox on the stack's GreenMail, read by tools-service with
the DEV_IMAP_PASSWORD secret. Sending the same notice twice starts nothing the second time: the trigger keys a run on
the message's ID and content.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "mailbox" / "levy_notice.json"


def message(item: dict[str, Any], to: str) -> EmailMessage:
    """The fixture, a Graph message item, as the email a court would send."""
    sender = item["from"]["emailAddress"]
    m = EmailMessage()
    m["From"] = f"{sender.get('name', '')} <{sender['address']}>"
    m["To"] = to
    m["Subject"] = item["subject"]
    m["Message-ID"] = item["internetMessageId"]
    m.set_content(str(item["body"]["content"]))
    attachments: list[dict[str, Any]] = list(item.get("attachments") or [])
    for a in attachments:
        main, _, sub = str(a["contentType"]).partition("/")
        m.add_attachment(base64.b64decode(a["contentBytes"]), maintype=main, subtype=sub, filename=a["name"])
    return m


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mailbox", default="levy@harborpine.example")
    ap.add_argument("--fixture", type=Path, default=FIXTURE, help="a Graph message item with its attachments")
    ap.add_argument("--smtp-port", type=int, default=int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025")))
    ap.add_argument(
        "--key-suffix",
        help="send the notice as a new message: the suffix goes into its Message-ID and subject, so the trigger does "
        "not take it for a redelivery of the fixture",
    )
    args = ap.parse_args()

    item: dict[str, Any] = json.loads(args.fixture.read_text())
    if args.key_suffix:
        suffix = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in args.key_suffix)
        local, _, domain = str(item["internetMessageId"]).strip("<>").partition("@")
        item["internetMessageId"] = f"<{local}-{suffix}@{domain}>"
        item["subject"] = f"{item['subject']} [{suffix}]"
    with smtplib.SMTP("127.0.0.1", args.smtp_port) as s:
        s.send_message(message(item, args.mailbox))
    print(f"sent {item['subject']!r} to {args.mailbox}; the worker reads it on its next pass")


if __name__ == "__main__":
    main()
