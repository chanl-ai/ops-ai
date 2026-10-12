"""Tokens and step-ups, by failure mode: a forged token, an expired one, one minted for another purpose or person,
and an algorithm swap."""

from __future__ import annotations

import pytest

from ops_policy import HmacSigner, TokenError, mint, mint_step_up, verify, verify_step_up
from ops_policy.tokens import _b64  # pyright: ignore[reportPrivateUsage]

KEY = HmacSigner.derived("review-secret", "step-up")
NOW = 1_800_000_000.0


def reason(fn: object, *args: object, **kw: object) -> str:
    with pytest.raises(TokenError) as e:
        fn(*args, **kw)  # type: ignore[operator]
    return e.value.reason


def test_step_up_round_trip() -> None:
    token = mint_step_up("dana@bank.test", KEY, now=NOW)
    assert verify_step_up(token, "dana@bank.test", KEY, now=NOW + 60).subject == "dana@bank.test"


def test_forged_step_up_is_refused() -> None:
    forged = mint_step_up("dana@bank.test", HmacSigner(b"guessed"), now=NOW)
    assert reason(verify_step_up, forged, "dana@bank.test", KEY, now=NOW) == "signature"


def test_expired_step_up_is_refused() -> None:
    token = mint_step_up("dana@bank.test", KEY, now=NOW)
    assert reason(verify_step_up, token, "dana@bank.test", KEY, now=NOW + 301) == "expired"


def test_step_up_for_another_subject_is_refused() -> None:
    token = mint_step_up("dana@bank.test", KEY, now=NOW)
    assert reason(verify_step_up, token, "omar@bank.test", KEY, now=NOW) == "subject"


def test_token_for_another_purpose_is_refused() -> None:
    # Same secret, different purpose: an approval-token key never verifies a step-up.
    other = mint_step_up("dana@bank.test", HmacSigner.derived("review-secret", "approval"), now=NOW)
    assert reason(verify_step_up, other, "dana@bank.test", KEY, now=NOW) == "signature"
    not_step_up = mint({"sub": "dana@bank.test"}, KEY, ttl_s=300, now=NOW)
    assert reason(verify_step_up, not_step_up, "dana@bank.test", KEY, now=NOW) == "type"


def test_shorter_window_than_minted_is_enforced() -> None:
    token = mint_step_up("dana@bank.test", KEY, now=NOW, ttl_s=3600)
    assert reason(verify_step_up, token, "dana@bank.test", KEY, now=NOW + 400) == "too_old"


def test_algorithm_none_is_refused() -> None:
    token = mint({"sub": "x"}, KEY, ttl_s=60, now=NOW)
    _, payload, _ = token.split(".")
    unsigned = f"{_b64(b'{"alg":"none","typ":"JWT"}')}.{payload}."
    assert reason(verify, unsigned, KEY, now=NOW) == "algorithm"
    assert reason(verify, "not-a-token", KEY, now=NOW) == "malformed"
