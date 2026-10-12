"""Canonical JSON per RFC 8785 (JSON Canonicalization Scheme), plus NFC on strings, and the input hash built on it.

An approval binds the hash of a call's input, and the hash is recomputed wherever the call is checked, by code that
may not be Python. Python's `json.dumps(sort_keys=True)` differs from JCS where it matters for that: it writes `24.0`
where JCS writes `24`, `1e-07` where JCS writes `1e-7`, and sorts keys by code point where JCS sorts by UTF-16 code
unit. JCS also rejects NaN and the infinities, which `json.dumps` writes as bare words no other parser accepts.

One deliberate addition to the RFC: strings and keys are normalised to NFC first, so a name typed with a combining
accent and the same name typed precomposed hash the same. The RFC leaves strings as they are.
"""

from __future__ import annotations

import hashlib
import math
import unicodedata
from decimal import Decimal
from typing import Any, cast

# Integers beyond this are not exactly representable as an IEEE 754 double, the only number type JCS has.
MAX_SAFE_INTEGER = 2**53 - 1

_ESCAPES = {'"': '\\"', "\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t"}


class CanonicalJsonError(ValueError):
    """The value has no canonical JSON form: NaN or an infinity, a non-string key, a lone surrogate, or a type JSON
    does not have."""


def canonicalize(value: Any) -> str:
    """The RFC 8785 serialisation of `value` (with NFC strings)."""
    out: list[str] = []
    _write(value, out)
    return "".join(out)


def input_hash(value: Any) -> str:
    """sha256 of the canonical form, hex: what an approval token binds."""
    return hashlib.sha256(canonicalize(value).encode()).hexdigest()


def _write(value: Any, out: list[str]) -> None:
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif isinstance(value, str):
        out.append(_string(value))
    elif isinstance(value, int):
        out.append(_integer(value))
    elif isinstance(value, float):
        out.append(number(value))
    elif isinstance(value, dict):
        _object(cast(dict[Any, Any], value), out)
    elif isinstance(value, list | tuple):
        out.append("[")
        for i, item in enumerate(cast(list[Any], value)):
            if i:
                out.append(",")
            _write(item, out)
        out.append("]")
    else:
        raise CanonicalJsonError(f"{type(value).__name__} has no JSON form")


def _object(value: dict[Any, Any], out: list[str]) -> None:
    keys: dict[str, Any] = {}
    for k, v in value.items():
        if not isinstance(k, str):
            raise CanonicalJsonError(f"object keys must be strings, not {type(k).__name__}")
        nk = unicodedata.normalize("NFC", k)
        if nk in keys:
            raise CanonicalJsonError(f"two keys normalise to the same string: {nk!r}")
        keys[nk] = v
    out.append("{")
    # RFC 8785 3.2.3: by UTF-16 code units, which differs from code point order for characters above U+FFFF.
    for i, k in enumerate(sorted(keys, key=lambda s: s.encode("utf-16-be"))):
        if i:
            out.append(",")
        out.append(_string(k))
        out.append(":")
        _write(keys[k], out)
    out.append("}")


def _string(value: str) -> str:
    s = unicodedata.normalize("NFC", value)
    try:
        s.encode("utf-8")
    except UnicodeEncodeError as e:
        raise CanonicalJsonError("string contains a lone surrogate") from e
    parts = ['"']
    for ch in s:
        if ch in _ESCAPES:
            parts.append(_ESCAPES[ch])
        elif ord(ch) < 0x20:
            parts.append(f"\\u{ord(ch):04x}")
        else:
            parts.append(ch)
    parts.append('"')
    return "".join(parts)


def _integer(value: int) -> str:
    if abs(value) <= MAX_SAFE_INTEGER:
        return str(value)
    # What a JavaScript or other IEEE 754 parser would read this as; refusing would reject valid JSON.
    return number(float(value))


def number(value: float) -> str:
    """ECMAScript Number.prototype.toString for a finite double (RFC 8785 3.2.2.3)."""
    if math.isnan(value) or math.isinf(value):
        raise CanonicalJsonError("NaN and the infinities have no JSON form")
    if value == 0:
        return "0"  # -0 included
    if value < 0:
        return "-" + number(-value)
    # repr gives the shortest digits that round-trip, as ECMAScript requires; only the layout differs.
    digits_t, exponent = cast(tuple[int, tuple[int, ...], int], Decimal(repr(value)).as_tuple())[1:]
    digits = "".join(map(str, digits_t)).rstrip("0") or "0"
    k = len(digits)
    n = len(digits_t) + exponent  # the decimal point sits after n digits
    if k <= n <= 21:
        return digits + "0" * (n - k)
    if 0 < n <= 21:
        return f"{digits[:n]}.{digits[n:]}"
    if -6 < n <= 0:
        return f"0.{'0' * -n}{digits}"
    e = n - 1
    mantissa = digits if k == 1 else f"{digits[0]}.{digits[1:]}"
    return f"{mantissa}e{'+' if e >= 0 else '-'}{abs(e)}"
