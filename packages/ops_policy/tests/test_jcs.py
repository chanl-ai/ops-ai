"""Canonical JSON against RFC 8785's own examples, the three places Python's json module disagrees with it, and the
values with no canonical form."""

from __future__ import annotations

import json
import math
import struct

import pytest

from ops_policy import CanonicalJsonError, canonicalize, input_hash


def double(bits: int) -> float:
    return struct.unpack(">d", bits.to_bytes(8, "big"))[0]


# RFC 8785 Appendix B: IEEE 754 bit patterns and their required serialisation.
APPENDIX_B = [
    (0x0000000000000000, "0"),
    (0x8000000000000000, "0"),
    (0x0000000000000001, "5e-324"),
    (0x8000000000000001, "-5e-324"),
    (0x7FEFFFFFFFFFFFFF, "1.7976931348623157e+308"),
    (0xFFEFFFFFFFFFFFFF, "-1.7976931348623157e+308"),
    (0x4340000000000000, "9007199254740992"),
    (0xC340000000000000, "-9007199254740992"),
    (0x4430000000000000, "295147905179352830000"),
    (0x44B52D02C7E14AF5, "9.999999999999997e+22"),
    (0x44B52D02C7E14AF6, "1e+23"),
    (0x44B52D02C7E14AF7, "1.0000000000000001e+23"),
    (0x444B1AE4D6E2EF4E, "999999999999999700000"),
    (0x444B1AE4D6E2EF4F, "999999999999999900000"),
    (0x444B1AE4D6E2EF50, "1e+21"),
    (0x3EB0C6F7A0B5ED8C, "9.999999999999997e-7"),
    (0x3EB0C6F7A0B5ED8D, "0.000001"),
    (0x41B3DE4355555553, "333333333.3333332"),
    (0x41B3DE4355555554, "333333333.33333325"),
    (0x41B3DE4355555555, "333333333.3333333"),
    (0x41B3DE4355555556, "333333333.3333334"),
    (0x41B3DE4355555557, "333333333.33333343"),
    (0xBECBF647612F3696, "-0.0000033333333333333333"),
    (0x43143FF3C1CB0959, "1424953923781206.2"),
]


@pytest.mark.parametrize(("bits", "expected"), APPENDIX_B)
def test_numbers_match_appendix_b(bits: int, expected: str) -> None:
    assert canonicalize(double(bits)) == expected


def test_section_3_2_2_sample() -> None:
    # The RFC's input string, built from code points so no editor or tool can reinterpret its escapes:
    # euro sign, $, U+000F, newline, A, apostrophe, B, quote, backslash, backslash, quote, slash.
    string = "".join(map(chr, [0x20AC, 0x24, 0x0F, 0x0A, 0x41, 0x27, 0x42, 0x22, 0x5C, 0x5C, 0x22, 0x2F]))
    value = {
        "numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
        "string": string,
        "literals": [None, True, False],
    }
    bs, q = chr(0x5C), chr(0x22)
    expected_string = chr(0x20AC) + "$" + bs + "u000f" + bs + "n" + "A'B" + bs + q + bs + bs + bs + bs + bs + q + "/"
    expected = (
        '{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"'
        + expected_string
        + '"}'
    )
    assert canonicalize(value) == expected


def test_section_3_2_3_key_order_is_by_utf16_code_unit() -> None:
    keys = ["\u20ac", "\r", "1", "\U0001f600", "\u0080", "\u00f6"]
    out = canonicalize(dict.fromkeys(keys, 0))
    assert list(json.loads(out)) == ["\r", "1", "\u0080", "\u00f6", "\u20ac", "\U0001f600"]


def test_divergence_float_and_int_of_one_value_hash_the_same() -> None:
    # json.dumps writes 24.0 for the float and 24 for the int, so an approval of {"amount": 24} would be refused when
    # the executor sends 24.0. JCS writes both as 24.
    assert json.dumps(24.0) != json.dumps(24)
    assert input_hash({"amount": 24}) == input_hash({"amount": 24.0})


def test_divergence_small_exponent_has_no_leading_zero() -> None:
    assert json.dumps(1e-7) == "1e-07"
    assert canonicalize(1e-7) == "1e-7"


def test_divergence_astral_keys_sort_before_private_use() -> None:
    # Code point order puts U+E000 first; UTF-16 code units put the surrogate pair (0xD83D...) first.
    value = {"\ue000": 1, "\U0001f600": 2}
    assert list(json.loads(json.dumps(value, sort_keys=True))) == ["\ue000", "\U0001f600"]
    assert list(json.loads(canonicalize(value))) == ["\U0001f600", "\ue000"]


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, {"amount": math.nan}])
def test_nan_and_infinity_are_rejected(bad: object) -> None:
    with pytest.raises(CanonicalJsonError):
        canonicalize(bad)


def test_strings_are_nfc_normalised() -> None:
    # A deliberate addition to RFC 8785: the same name typed decomposed or precomposed hashes the same.
    assert input_hash({"payee": "Jose\u0301"}) == input_hash({"payee": "Jos\u00e9"})


def test_other_rejections() -> None:
    with pytest.raises(CanonicalJsonError):
        canonicalize({1: "a"})
    with pytest.raises(CanonicalJsonError):
        canonicalize("\ud800")
    with pytest.raises(CanonicalJsonError):
        canonicalize({"Jose\u0301": 1, "Jos\u00e9": 2})


def test_large_integers_serialise_as_a_double_would() -> None:
    assert canonicalize(2**53) == "9007199254740992"
    assert canonicalize(10**21) == "1e+21"
