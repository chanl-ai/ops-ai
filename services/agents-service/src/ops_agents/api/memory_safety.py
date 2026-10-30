"""Numbers a memory must never hold (c-563), found by fixed rules whatever the model says: card numbers by the Luhn
check, IBANs by their mod-97 check digits, and United States, United Kingdom and Canadian national ids by their issuing
rules (Canada's also by Luhn). Other countries' ids come with the memory policy's sensitive rules."""

from __future__ import annotations

import re

CARD = "card number"
IBAN = "IBAN"
NATIONAL_ID = "national id"

_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
# Written in capitals, as banks print them; matching any case would run on into the next word.
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
# Never issued: area 000, 666 or 900-999, group 00, serial 0000.
_SSN = re.compile(r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])")
# Two prefix letters (neither D, F, I, Q, U or V, the second not O, and not one of the never-issued pairs), six digits
# and a suffix A to D.
_NINO = re.compile(r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TW-Z][A-CEGHJ-NPR-TW-Z] ?\d{2} ?\d{2} ?\d{2} ?[A-D]\b")
_SIN = re.compile(r"(?<![\d-])\d{3}[ -]?\d{3}[ -]?\d{3}(?![\d-])")


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch) * (2 if i % 2 else 1)
        total += d - 9 if d > 9 else d
    return total % 10 == 0


def _iban(candidate: str) -> bool:
    text = candidate.replace(" ", "").upper()
    moved = text[4:] + text[:4]
    return int("".join(str(int(ch, 36)) for ch in moved)) % 97 == 1


def sensitive(text: str) -> str | None:
    """The kind of number in `text` a memory must never hold, or None."""
    if any(_luhn(_digits(m.group())) for m in _CARD.finditer(text)):
        return CARD
    if any(_iban(m.group()) for m in _IBAN.finditer(text)):
        return IBAN
    if _SSN.search(text) or _NINO.search(text) or any(_luhn(_digits(m.group())) for m in _SIN.finditer(text)):
        return NATIONAL_ID
    return None
