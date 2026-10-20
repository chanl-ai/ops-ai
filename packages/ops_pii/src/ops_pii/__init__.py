"""Personal data masked in what people see (c-293): SSNs and their last four, card and account
numbers, emails and phone numbers. Names are not masked: no pattern finds them without a model call. A caller decides
what is shown; the real value stays wherever it is kept or sent on (an agent's model, a document type's examples).

A pattern is masked whole, never a part of it: streamed text is held back by HOLD characters and cut only at
whitespace, so a number arriving across two chunks is masked as one, and an email (no whitespace in it) is never cut.
"""

from __future__ import annotations

import re

# Longer than the longest pattern that may contain a space (a spaced card number, a spaced phone number).
HOLD = 32

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
_PHONE = re.compile(r"(?<![\d+])(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)")
# A digit run long enough to be an account number and too long to be an amount, a year or a date. A run glued to letters
# or an underscore is part of an id (fil_13cf059e9367473281ca9d...), never a number on its own: ids are not masked.
_ACCOUNT = re.compile(r"(?<![\w,.])\d{8,17}(?![\w,.])")
# The digits after an SSN, card or account word ("SSN ending 6789", "account no. 4410", "card ****4410").
_WORDS = r"(?i)\b(ssn|social security(?: number)?|account|acct|card)\b"
_BETWEEN = r"((?:\s+(?:number|no\.?|#|ending|ends|in|with))*\s*[:#]?\s*\**)"
_TAIL = re.compile(_WORDS + _BETWEEN + r"(\d{4,17})\b")
# The same words still waiting for their digits at the end of released text: a cut must come before them.
_OPEN_TAIL = re.compile(_WORDS + _BETWEEN + r"$")


def mask(text: str) -> str:
    """`text` with each pattern replaced by what it is: [email], [SSN], [card], [phone], [account], or the digits after
    an SSN, account or card word as ••••."""
    text = _EMAIL.sub("[email]", text)
    text = _SSN.sub("[SSN]", text)
    text = _CARD.sub("[card]", text)
    text = _PHONE.sub("[phone]", text)
    text = _TAIL.sub(lambda m: f"{m.group(1)}{m.group(2)}••••", text)
    return _ACCOUNT.sub("[account]", text)


class StreamMasker:
    """Masks streamed text without ever showing part of a pattern: text is released only up to whitespace at least HOLD
    characters back from the end, and the rest at `flush`."""

    def __init__(self) -> None:
        self.pending = ""

    def push(self, delta: str) -> str:
        self.pending += delta
        limit = len(self.pending) - HOLD
        if limit <= 0:
            return ""
        cut = max((i + 1 for i in range(limit) if self.pending[i].isspace()), default=0)
        if (opened := _OPEN_TAIL.search(self.pending[:cut])) is not None:
            cut = opened.start()
        if cut == 0:
            return ""
        out, self.pending = self.pending[:cut], self.pending[cut:]
        return mask(out)

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        return mask(out)

    def reset(self) -> None:
        self.pending = ""
