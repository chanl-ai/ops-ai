"""Personal data masked in what people see: SSNs and their last four, card and account
numbers, emails and phone numbers. Names are not masked: no pattern finds them without a model call. A caller decides
what is shown; the real value stays wherever it is kept or sent on (an agent's model, a document type's examples).

A value is also masked by the name of its field, whatever it holds: a last four ("4471") or a lettered account id
("BUS-7781") matches no pattern on its own, and a number is not text at all. A field is named as personal data when its
name holds "ssn", or "account", "acct", "card", "tax" or "taxpayer" followed only by identifier words (id, ids, number,
no, last 4, ...): ssnLast4, accountIds, account_number, cardLast4, taxId. A name that only mentions one (accountName,
accountCount, cards, card_limit, tax) is not, so chat's cards and a tax amount stay readable. The name is a JSON key,
the label of a {label, value} row, or a key written in text ('accountId': 'BUS-7781', Account id BUS-7781).

A pattern is masked whole, never a part of it: streamed text is held back by HOLD characters and cut only at
whitespace, so a number arriving across two chunks is masked as one, and an email (no whitespace in it) is never cut.
"""

from __future__ import annotations

import re
from itertools import pairwise
from typing import Any, cast

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
# A record's number named as one ("Case 00045120", "order no. 1234567890"): eight digits is a Salesforce case number,
# not an account, so the digits after these words are left as they are.
_RECORD_WORDS = r"(?i)\b(?:case|ticket|order|invoice)(?:\s+(?:number|no\.?))?\s*#?\s*"
_RECORD = re.compile(_RECORD_WORDS + r"(?=\d)")
_OPEN_RECORD = re.compile(_RECORD_WORDS + r"$")
# The same words still waiting for their digits at the end of released text: a cut must come before them.
_OPEN_TAIL = re.compile(_WORDS + _BETWEEN + r"$")
# A field name still waiting for its value at the end of released text ("ssnLast4": , Tax ID ).
# An unquoted value after a field name: a dashed SSN, a lettered id, or digits in groups as a card number is written.
_BARE = r"-?[A-Za-z]{0,6}-?\d[\w.-]*(?: \d[\d-]*)*"
_OPEN_KEYED = re.compile(
    r"""(["']?)([A-Za-z][A-Za-z0-9_]*)\1\s*[:=]\s*(?:["']?|\[[^\[\]{}\n]*|""" + _BARE + r""" ?)$"""
)
_OPEN_LABELLED = re.compile(
    r"(?i)\b(?:ssn|account|acct|card|tax(?:payer)?)(?:\s+(?:id|number|no\.?|#))?(?:\s+last\s*4)?\s*[:#]?\s*$"
)


# The words of a field's name: camelCase, snake_case, spaced or upper case ("ssnLast4", "account_id", "Account id").
_NAME_WORDS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
# The word a name starts its identifier with, and what is shown in place of the value.
_KINDS = {"account": "[account]", "acct": "[account]", "card": "[card]", "tax": "[tax ID]", "taxpayer": "[tax ID]"}
# The words that may follow it: the name says the value identifies the account, card or taxpayer.
_ID_WORDS = frozenset(
    {"id", "ids", "number", "numbers", "num", "no", "nr", "last", "4", "four", "digits", "ein", "tin"}
)
# A key written in text with its value: JSON ("ssnLast4": "4471"), a Python repr ('accountId': 'BUS-7781') or key=value.
# An unquoted value is taken whole (_BARE), so a dashed SSN or a spaced card number is never masked in part.
_KEYED = re.compile(
    r"""(["']?)([A-Za-z][A-Za-z0-9_]*)\1(\s*[:=]\s*)(?:(["'])([^"'\n]*)\4|(""" + _BARE + r""")|\[([^\[\]{}\n]*)\])"""
)
# One item of a list written in text: a quoted text or a number.
_ITEM = re.compile(r"""(["'])[^"'\n]*\1|-?\d[\d.]*""")
# The name in words before the value, as a field is labelled in a sentence ("Account id BUS-7781", "Tax ID 98-7654321").
_LABELLED = re.compile(
    r"(?i)\b((?:ssn|account|acct|card|tax(?:payer)?)(?:\s+(?:id|number|no\.?|#))(?:\s+last\s*4)?)(\s*[:#]?\s*)"
    r"([A-Za-z]{0,6}-?\d[\w-]*)"
)


def field_kind(name: str) -> str | None:
    """What a value under the field `name` is shown as when the name says it is personal data: [SSN], [account],
    [card] or [tax ID]; None for any other name."""
    words = [w.lower() for w in _NAME_WORDS.findall(name)]
    if "ssn" in words or ("social", "security") in pairwise(words):
        return "[SSN]"
    for i, word in enumerate(words):
        rest = words[i + 1 :]
        if word in _KINDS and rest and all(w in _ID_WORDS for w in rest):
            return _KINDS[word]
    return None


def _keyed(m: re.Match[str]) -> str:
    shown = field_kind(m.group(2))
    if shown is None:
        return m.group(0)
    name = f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}"
    if m.group(7) is not None:
        items = _ITEM.sub(lambda i: f"{i.group(1)}{shown}{i.group(1)}" if i.group(1) else f'"{shown}"', m.group(7))
        return f"{name}[{items}]"
    if not (m.group(5) or m.group(6)):
        return m.group(0)
    quote = m.group(4) or m.group(1)
    return f"{name}{quote}{shown}{quote}"


def _labelled(m: re.Match[str]) -> str:
    shown = field_kind(m.group(1))
    return f"{m.group(1)}{m.group(2)}{shown}" if shown is not None else m.group(0)


def mask(text: str) -> str:
    """`text` with each pattern replaced by what it is: [email], [SSN], [card], [phone], [account], or the digits after
    an SSN, account or card word as ••••; a value written after a field name that names personal data is replaced
    whole ([tax ID] for a taxpayer's)."""
    text = _KEYED.sub(_keyed, text)
    text = _EMAIL.sub("[email]", text)
    text = _SSN.sub("[SSN]", text)
    text = _CARD.sub("[card]", text)
    text = _PHONE.sub("[phone]", text)
    text = _TAIL.sub(lambda m: f"{m.group(1)}{m.group(2)}••••", text)
    kept = {m.end() for m in _RECORD.finditer(text)}
    text = _ACCOUNT.sub(lambda m: m.group(0) if m.start() in kept else "[account]", text)
    # Last, so a number the patterns above mask whole (a spaced card number) is not cut at its first space.
    return _LABELLED.sub(_labelled, text)


def masked(value: Any, key: str | None = None) -> Any:
    """A JSON value as people see it: every string in it masked, and every value under a field whose name names personal
    data (`field_kind`) replaced whole, a number included; `key` is the name of the field `value` sits under. A
    {label, value} row is named by its label. A true or false, a null and an empty text are left: they say nothing."""
    shown = field_kind(key) if key else None
    if shown is not None:
        return _whole(value, shown)
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [masked(v) for v in cast(list[Any], value)]
    if isinstance(value, dict):
        row = cast(dict[Any, Any], value)
        label = row.get("label") if "value" in row else None
        named = field_kind(label) if isinstance(label, str) else None
        return {
            k: _whole(v, named) if named is not None and k == "value" else masked(v, str(k)) for k, v in row.items()
        }
    return value


def _whole(value: Any, shown: str) -> Any:
    """A personal data field's value with each scalar in it replaced by `shown`; an object in it is masked by its own
    field names, since a list of accounts holds names and balances too."""
    if value is None or isinstance(value, bool) or value == "":
        return value
    if isinstance(value, str | int | float):
        return shown
    if isinstance(value, list):
        return [_whole(v, shown) for v in cast(list[Any], value)]
    return masked(value)


# Everything `mask` writes in place of a pattern.
PLACEHOLDERS = ("[email]", "[SSN]", "[card]", "[phone]", "[account]", "[tax ID]", "••••")


def holds_placeholder(text: str) -> bool:
    """Whether `text` has a placeholder where `mask` took personal data out: the real value is not in it."""
    return any(p in text for p in PLACEHOLDERS)


def _opened(released: str) -> int | None:
    """Where text about to be released ends on a word or field name still waiting for its value, else None."""
    if (
        m := _OPEN_TAIL.search(released) or _OPEN_RECORD.search(released) or _OPEN_LABELLED.search(released)
    ) is not None:
        return m.start()
    if (m := _OPEN_KEYED.search(released)) is not None and field_kind(m.group(2)) is not None:
        return m.start()
    return None


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
        if (opened := _opened(self.pending[:cut])) is not None:
            cut = opened
        if cut == 0:
            return ""
        out, self.pending = self.pending[:cut], self.pending[cut:]
        return mask(out)

    def flush(self) -> str:
        out, self.pending = self.pending, ""
        return mask(out)

    def reset(self) -> None:
        self.pending = ""
