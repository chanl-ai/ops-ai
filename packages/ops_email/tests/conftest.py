"""Every test builds its Settings from what it passes: a developer's OPS_* environment (an `.env` exported by make, an
egress override) must not change which provider is picked or refuse a test's settings. The IMAP and SMTP tests talk to
the compose test mail servers (`make db-up`: GreenMail, Mailpit) and skip when they are not running."""

from __future__ import annotations

import os
import socket
import uuid

import pytest

# Read before the fixture below clears OPS_* for each test.
GREENMAIL_SMTP = int(os.environ.get("OPS_GREENMAIL_SMTP_PORT", "3025"))
GREENMAIL_IMAP = int(os.environ.get("OPS_GREENMAIL_IMAP_PORT", "3143"))
MAILPIT_SMTP = int(os.environ.get("OPS_MAILPIT_SMTP_PORT", "1025"))
MAILPIT_HTTP = int(os.environ.get("OPS_MAILPIT_HTTP_PORT", "8025"))


def listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


@pytest.fixture(autouse=True)
def _no_ops_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [n for n in os.environ if n.startswith("OPS_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def greenmail() -> str:
    """A fresh mailbox address on GreenMail: mail sent to it on the SMTP port is read over IMAP."""
    if not (listening(GREENMAIL_SMTP) and listening(GREENMAIL_IMAP)):
        pytest.skip("GreenMail is not running (make db-up)")
    return f"box-{uuid.uuid4().hex[:10]}@bank.example"


@pytest.fixture
def mailpit() -> str:
    """Mailpit's HTTP API; the SMTP port catches mail."""
    if not (listening(MAILPIT_SMTP) and listening(MAILPIT_HTTP)):
        pytest.skip("Mailpit is not running (make db-up)")
    return f"http://127.0.0.1:{MAILPIT_HTTP}"
