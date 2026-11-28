"""Personal data masked in what people see: SSNs and their last four, card and account
numbers, emails and phone numbers. Names are not masked: no pattern finds them without a model call. A caller decides
what is shown; the real value stays wherever it is kept or sent on (an agent's model, a document type's examples).

A value is also masked by the name of its field, whatever it holds: a last four ("4471") or a lettered account id
("BUS-7781") matches no pattern on its own, and a number is not text at all. A field is named as personal data when its
name holds "ssn", or "account", "acct", "iban", "card", "tax" or "taxpayer" followed only by identifier words (id, ids,
number, no, last 4, ref, code, key, token, ...), or account, acct, iban or card alone: ssnLast4, accountIds,
account_number, accountid, bankAccount, debitCard, card_token, taxId. A name that only mentions one (accountName,
accountCount, cards, card_limit, tax) is not, so chat's cards and a tax amount stay readable. The name is a JSON key
(an object under it has its identifiers masked: account.id, ssn.last4), the label, name, key or field of a
{label, value} row, or a key written in text: JSON, a repr, key=value, an arrow, a table cell, a tab, XML, or a call
worded "account_id CHQ-2219". A value with no digit is masked only after a separator, so prose about a field is kept.

A pattern is masked whole, never a part of it: streamed text is held back by HOLD characters and cut only at
whitespace, so a number arriving across two chunks is masked as one, and an email (no whitespace in it) is never cut.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from itertools import pairwise
from typing import Any, cast

# Longer than the longest pattern that may contain a space (a spaced card number, a spaced phone number).
HOLD = 32

# Every part is bounded so the search stays linear in long text with no address in it: the name before the @ reads up to
# 64 characters (the longest a mailbox name may be), each domain label up to 63, at most 8 labels and a top level of 24
# letters, and the whole domain at most 255 characters (RFC 5321, RFC 1035).
_EMAIL = re.compile(
    r"[A-Za-z0-9._%+-]{1,64}@(?=[A-Za-z0-9.-]{1,255}(?![A-Za-z0-9.-]))(?:[A-Za-z0-9-]{1,63}\.){1,8}[A-Za-z]{2,24}"
)
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
# A bare field name reads up to 64 characters: an unbounded \w* is tried from every letter of a long word with no
# separator after it, which takes time that grows with the square of its length.
# An unquoted value after a field name: a dashed SSN, a lettered id, or digits in groups as a card number is written.
_BARE = r"-?[A-Za-z]{0,6}-?\d[\w.-]*(?: \d[\d-]*)*"
_OPEN_KEYED = re.compile(
    r"""(?:(["'])([A-Za-z][\w ]*?)\1|()([A-Za-z]\w{0,63}))(?:\s*(?:[:=|]|->|=>|→)\s*|\t+)"""
    r"""(?:["']?|\[[^\[\]{}\n]*|""" + _BARE + r""" ?|[A-Za-z][\w.-]* ?)$"""
)
_OPEN_LABELLED = re.compile(
    r"(?i)\b(?:ssn|account|acct|card|tax(?:payer)?)(?:[\s_]+(?:id|number|no\.?|#))?(?:\s+last\s*4)?"
    r"\s*(?:[:#|]|->|=>|→)?\s*$"
)


def _name_words(name: str) -> list[str]:
    """The words of a field's name: camelCase, snake_case, spaced or upper case ("ssnLast4", "account_id", "Account
    id", "IBANNumber" as IBAN and Number). One pass over the name: a regex with a run of capitals before a lookahead
    backtracks over every capital, quadratic in a name of many."""
    out: list[str] = []
    i, n = 0, len(name)
    while i < n:
        c = name[i]
        j = i + 1
        if c.isdecimal():
            while j < n and name[j].isdecimal():
                j += 1
        elif "A" <= c <= "Z":
            while j < n and "A" <= name[j] <= "Z":
                j += 1
            if j < n and "a" <= name[j] <= "z":
                if j - i > 1:
                    # The last capital starts the next word ("IBANNumber").
                    out.append(name[i : j - 1])
                    i = j - 1
                    continue
                while j < n and "a" <= name[j] <= "z":
                    j += 1
        elif "a" <= c <= "z":
            while j < n and "a" <= name[j] <= "z":
                j += 1
        else:
            i = j
            continue
        out.append(name[i:j])
        i = j
    return out


# The word a name starts its identifier with, and what is shown in place of the value.
_KINDS = {
    "account": "[account]", "acct": "[account]", "iban": "[account]", "card": "[card]", "tax": "[tax ID]",
    "taxpayer": "[tax ID]",
}  # fmt: skip
# Kinds that name the identifier on their own (account, bankAccount, debitCard, iban); a bare "tax" is an amount.
_ALONE = frozenset({"account", "acct", "iban", "card"})
# The words that may follow it: the name says the value identifies the account, card or taxpayer.
_ID_WORDS = frozenset(
    {
        "id", "ids", "number", "numbers", "num", "no", "nr", "last", "4", "four", "digits", "ein", "tin", "ref",
        "reference", "code", "key", "token",
    }
)  # fmt: skip
# What a bare `account` says when it names which account a connection signs in with, not an identifier: tools-service's
# "account": "team" or "own" (a connection's health, a reconnect refusal). Under an identifier word it is still masked.
_ACCOUNT_SORTS = frozenset({"team", "own"})
# Plural identifier words: an object under such a name (accountIds: {checking: ...}) holds only identifiers.
_PLURAL = frozenset({"ids", "numbers"})
# The words a lower case name with no break is read as ("accountid", "ssnlast4"), longest first.
_GLUED = sorted({"ssn", *_KINDS, *_ID_WORDS}, key=len, reverse=True)
# A key written in text with its value: JSON ("ssnLast4": "4471"), a Python repr ('accountId': 'BUS-7781'), key=value,
# an arrow, a table cell or a tab. An unquoted value is taken whole (_BARE), so a dashed SSN or a spaced card number is
# never masked in part; one with no digit is taken only as a word after a separator, never a null, true or false.
_SEP = r"(?:\s*(?:[:=|]|->|=>|→)\s*|\t+)"
_WORD_VALUE = r"(?!(?i:null|none|true|false|undefined)\b)[A-Za-z][\w.-]*"
_KEYED = re.compile(
    r"""(?:(["'])([A-Za-z][\w ]*?)\1|()([A-Za-z]\w{0,63}))("""
    + _SEP
    + r""")(?:(["'])([^"'\n]*)\6|("""
    + _BARE
    + r"|"
    + _WORD_VALUE
    + r""")|\[([^\[\]{}\n]*)\])"""
)
# XML: <accountId>BUS-7781</accountId>.
_XML = re.compile(r"<([A-Za-z][\w.-]*)(\s[^<>]*)?>([^<>]*)</\1>")
_OPEN_NAME = re.compile(r"""["']([A-Za-z][\w ]*)["']?\s*$|\b([A-Za-z]\w*)\s*$""")
_OPEN_XML = re.compile(r"<([A-Za-z][\w.-]*)(?:\s[^<>]*)?>[^<>]*$")
# One item of a list written in text: a quoted text or a number.
_ITEM = re.compile(r"""(["'])[^"'\n]*\1|-?\d[\d.]*""")
# The name in words before the value, as a field is labelled in a sentence ("Account id BUS-7781", "Tax ID 98-7654321")
# or a call is worded ("place_hold: account_id CHQ-2219"); the value holds a digit, so prose about the field is kept.
_LABEL = r"(?:ssn|account|acct|card|tax(?:payer)?)(?:[\s_]+(?:id|number|no\.?|#))(?:\s+last\s*4)?"
_LABELLED = re.compile(r"(?i)\b(" + _LABEL + r")(\s*(?:[:#|]|->|=>|→)?\s*)([A-Za-z]{0,12}-?\d[\w-]*)")


def _words(name: str) -> list[str]:
    """The words of a field name, a lower case word with no break read by the words it is made of ("accountid")."""
    words: list[str] = []
    for word in (w.lower() for w in _name_words(name)):
        parts: list[str] = []
        rest = word
        while rest:
            part = next((g for g in _GLUED if rest.startswith(g)), None)
            if part is None:
                break
            parts.append(part)
            rest = rest[len(part) :]
        words.extend(parts if not rest and len(parts) > 1 else [word])
    return words


def field_kind(name: str) -> str | None:
    """What a value under the field `name` is shown as when the name says it is personal data: [SSN], [account],
    [card] or [tax ID]; None for any other name."""
    words = _words(name)
    if "ssn" in words or ("social", "security") in pairwise(words):
        return "[SSN]"
    for i, word in enumerate(words):
        rest = words[i + 1 :]
        if word in _KINDS and (rest or word in _ALONE) and all(w in _ID_WORDS for w in rest):
            return _KINDS[word]
    return None


def says_which_account(name: str, value: object) -> bool:
    """Whether `value` under the field `name` names which account is used (team, own) rather than identifying one: a
    bare account name with one of those words."""
    return isinstance(value, str) and value.lower() in _ACCOUNT_SORTS and _words(name) in (["account"], ["acct"])


def _keyed(m: re.Match[str]) -> str:
    key = m.group(2) if m.group(2) is not None else m.group(4)
    shown = field_kind(key)
    if shown is None:
        return m.group(0)
    quote_key = m.group(1) or ""
    name = f"{quote_key}{key}{quote_key}{m.group(5)}"
    if m.group(9) is not None:
        items = _ITEM.sub(lambda i: f"{i.group(1)}{shown}{i.group(1)}" if i.group(1) else f'"{shown}"', m.group(9))
        return f"{name}[{items}]"
    if not (m.group(7) or m.group(8)) or says_which_account(key, m.group(7) or m.group(8)):
        return m.group(0)
    quote = m.group(6) or quote_key
    return f"{name}{quote}{shown}{quote}"


def _keyed_values(text: str) -> str:
    """`text` with each value written after a personal data field name replaced (`_keyed`). A match under any other
    name gives back only its name, so a field written as its value ("customer: accountId: ABCDEFG") is still read."""
    out: list[str] = []
    pos = 0
    while (m := _KEYED.search(text, pos)) is not None:
        key = m.group(2) if m.group(2) is not None else m.group(4)
        loose = (m.group(8) is not None and not re.search(r"\d", m.group(8))) or "|" in m.group(5) or "\t" in m.group(5)
        # A word with no digit, or a table cell or a tab after the name, is its value only when the name says it is an
        # identifier (accountId: ABCDEFG); after a name alone it is prose or a heading ("the account: it has").
        if field_kind(key) is None or (loose and not any(w in _ID_WORDS for w in _words(key))):
            out.append(text[pos : m.end(5)])
            pos = m.end(5)
            continue
        out.append(text[pos : m.start()] + _keyed(m))
        pos = m.end()
    return "".join(out) + text[pos:]


def _xml(m: re.Match[str]) -> str:
    shown = field_kind(m.group(1))
    if shown is None or not m.group(3).strip():
        return m.group(0)
    return f"<{m.group(1)}{m.group(2) or ''}>{shown}</{m.group(1)}>"


def _labelled(m: re.Match[str]) -> str:
    shown = field_kind(m.group(1))
    return f"{m.group(1)}{m.group(2)}{shown}" if shown is not None else m.group(0)


def mask(text: str) -> str:
    """`text` with each pattern replaced by what it is: [email], [SSN], [card], [phone], [account], or the digits after
    an SSN, account or card word as ••••; a value written after a field name that names personal data is replaced
    whole ([tax ID] for a taxpayer's)."""
    text = _keyed_values(text)
    text = _XML.sub(_xml, text)
    text = _EMAIL.sub("[email]", text)
    text = _SSN.sub("[SSN]", text)
    text = _CARD.sub("[card]", text)
    text = _PHONE.sub("[phone]", text)
    text = _TAIL.sub(lambda m: f"{m.group(1)}{m.group(2)}••••", text)
    kept = {m.end() for m in _RECORD.finditer(text)}
    text = _ACCOUNT.sub(lambda m: m.group(0) if m.start() in kept else "[account]", text)
    # Last, so a number the patterns above mask whole (a spaced card number) is not cut at its first space.
    return _LABELLED.sub(_labelled, text)


# The names a row ({label, value}) is named by: a form's label, a record's name, key or field.
_ROW_NAMES = ("label", "name", "key", "field")


def _row_name(row: dict[Any, Any]) -> str | None:
    """What a {label, value} row's value is shown as, by the first of its names that names personal data."""
    if "value" not in row:
        return None
    for k in _ROW_NAMES:
        if isinstance(name := row.get(k), str) and (shown := field_kind(name)) is not None:
            return None if says_which_account(name, row["value"]) else shown
    return None


def masked(
    value: Any,
    key: str | None = None,
    *,
    keep: frozenset[str] = frozenset(),
    text: Callable[[str], str] = mask,
    hidden: Callable[[str, Any], Any] | None = None,
) -> Any:
    """A JSON value as people see it: every string in it masked (`text`, `mask` by default), and every value under a
    field whose name names personal data (`field_kind`) replaced whole, a number included; `key` is the name of the
    field `value` sits under. A {label, value} row is named by its label (or its name, key or field). A true or false,
    a null and an empty text are left: they say nothing. This is the one walk of JSON by key: every reader that masks
    one calls it.

    `keep` names the fields of the top object whose text is shown as it is (a task's ids and state); below the top it
    names nothing, so a tool input's own `id` or `status` is masked like any other value. `hidden`, given a field name
    and its value, returns what is shown in its place (a log's secrets) or None to mask it as usual."""
    return _walk(value, key, keep, text, hidden)


def _walk(
    value: Any,
    key: str | None,
    keep: frozenset[str],
    text: Callable[[str], str],
    hidden: Callable[[str, Any], Any] | None,
) -> Any:
    shown = field_kind(key) if key else None
    if shown is not None and not says_which_account(key or "", value):
        return _whole(value, shown, key or "", text, hidden)
    if shown is not None:
        return value
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list | tuple | set | frozenset):
        return [_walk(v, key, frozenset(), text, hidden) for v in cast(list[Any], value)]
    if isinstance(value, Mapping):
        row = cast(dict[Any, Any], value)
        named = _row_name(row)
        out: dict[Any, Any] = {}
        for k, v in row.items():
            name = str(k)
            if hidden is not None and (instead := hidden(name, v)) is not None:
                out[k] = instead
            elif name in keep and not isinstance(v, Mapping | list):
                out[k] = v
            elif named is not None and k == "value":
                out[k] = _whole(v, named, name, text)
            else:
                out[k] = _walk(v, name, frozenset(), text, hidden)
        return out
    return value


class _Hidden:
    """What `hidden` shows in place of a field inside a personal data field's object, kept apart from its masking."""

    def __init__(self, shown: Any) -> None:
        self.shown = shown


# Where an object under a personal data field holds that field's value: a field as a document read records it.
_CELL_VALUES = ("value", "extractedValue")


def _whole(
    value: Any,
    shown: str,
    key: str,
    text: Callable[[str], str] = mask,
    hidden: Callable[[str, Any], Any] | None = None,
) -> Any:
    """A personal data field's value with each scalar in it replaced by `shown`. An object in it keeps what is not an
    identifier (a list of accounts holds names and balances too): a field named by identifier words alone (account.id,
    ssn.last4) is masked as the field, and under a plural name (accountIds) every field is. An object holding the
    field's value under `value` (a document read's field: its value, the value read, its confidence and the page quote)
    has that value replaced, and a text in it that is the value itself (a quote of it alone); the value is never
    replaced as a part of a longer text, where it may be any number."""
    if value is None or isinstance(value, bool) or value == "":
        return value
    if isinstance(value, str | int | float):
        return shown
    if isinstance(value, list | tuple | set | frozenset):
        return [_whole(v, shown, key, text, hidden) for v in cast(list[Any], value)]
    row = cast(dict[Any, Any], value)
    if hidden is not None:
        row = {k: v if (instead := hidden(str(k), v)) is None else _Hidden(instead) for k, v in row.items()}
    if "value" not in row:
        every = bool(_PLURAL & set(_words(key)))
        return {
            k: v.shown
            if isinstance(v, _Hidden)
            else _whole(v, shown, key, text, hidden)
            if every or all(w in _ID_WORDS for w in _words(str(k)))
            else _walk(v, str(k), frozenset(), text, hidden)
            for k, v in row.items()
        }
    real = {
        str(row[k]).strip()
        for k in _CELL_VALUES
        if isinstance(row.get(k), str | int | float) and not isinstance(row.get(k), bool) and row.get(k) != ""
    }
    return {
        k: v.shown
        if isinstance(v, _Hidden)
        else _whole(v, shown, key, text, hidden)
        if k in _CELL_VALUES
        else _quoted(_walk(v, str(k), frozenset(), text, hidden), real, shown)
        for k, v in row.items()
    }


def _quoted(value: Any, real: set[str], shown: str) -> Any:
    """`value` with every text in it that is one of `real` alone replaced by `shown`."""
    if isinstance(value, str):
        return shown if value.strip() in real else value
    if isinstance(value, list):
        return [_quoted(v, real, shown) for v in cast(list[Any], value)]
    if isinstance(value, dict):
        return {k: _quoted(v, real, shown) for k, v in cast(dict[Any, Any], value).items()}
    return value


# Everything `mask` writes in place of a pattern.
PLACEHOLDERS = ("[email]", "[SSN]", "[card]", "[phone]", "[account]", "[tax ID]", "••••")


def holds_placeholder(text: str) -> bool:
    """Whether `text` has a placeholder where `mask` took personal data out: the real value is not in it."""
    return any(p in text for p in PLACEHOLDERS)


def _opened(released: str) -> int | None:
    """Where text about to be released ends on a word or field name still waiting for its value, else None: the
    earliest such start, so a quote or a bracket before a name is held with it."""
    starts = [
        m.start() for m in (_OPEN_TAIL.search(released), _OPEN_RECORD.search(released), _OPEN_LABELLED.search(released))
        if m is not None
    ]  # fmt: skip
    named = ((_OPEN_KEYED, (2, 4)), (_OPEN_XML, (1,)), (_OPEN_NAME, (1, 2)))
    for pattern, groups in named:
        m = pattern.search(released)
        if m is not None and field_kind(next((g for g in (m.group(i) for i in groups) if g), "")) is not None:
            starts.append(m.start())
    return min(starts, default=None)


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
