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


DANA = "dana@bank.test"


@pytest.mark.parametrize(
    ("signer", "ttl_s", "subject", "after_s", "why"),
    [
        (HmacSigner(b"guessed"), 300, DANA, 0, "signature"),
        (KEY, 300, DANA, 301, "expired"),
        (KEY, 300, "omar@bank.test", 0, "subject"),
        # Same secret, different purpose: an approval-token key never verifies a step-up.
        (HmacSigner.derived("review-secret", "approval"), 300, DANA, 0, "signature"),
        # A window shorter than the one minted is enforced.
        (KEY, 3600, DANA, 400, "too_old"),
    ],
    ids=["forged", "expired", "another-subject", "another-purpose", "shorter-window"],
)
def test_a_step_up_that_proves_nothing_is_refused(
    signer: HmacSigner, ttl_s: int, subject: str, after_s: int, why: str
) -> None:
    token = mint_step_up(DANA, signer, now=NOW, ttl_s=ttl_s)
    assert reason(verify_step_up, token, subject, KEY, now=NOW + after_s) == why


def test_a_token_that_is_not_a_step_up_is_refused() -> None:
    not_step_up = mint({"sub": DANA}, KEY, ttl_s=300, now=NOW)
    assert reason(verify_step_up, not_step_up, DANA, KEY, now=NOW) == "type"


def test_algorithm_none_is_refused() -> None:
    token = mint({"sub": "x"}, KEY, ttl_s=60, now=NOW)
    _, payload, _ = token.split(".")
    unsigned = f"{_b64(b'{"alg":"none","typ":"JWT"}')}.{payload}."
    assert reason(verify, unsigned, KEY, now=NOW) == "algorithm"
    assert reason(verify, "not-a-token", KEY, now=NOW) == "malformed"


def test_a_token_issued_a_second_ahead_of_this_clock_still_verifies() -> None:
    """A clock stepped back after the machine wakes puts a fresh token's `iat` ahead of the verifier's clock."""
    token = mint({"sub": "x"}, KEY, ttl_s=60, now=NOW + 1)
    assert verify(token, KEY, now=NOW)["sub"] == "x"
    assert reason(verify, mint({"sub": "x"}, KEY, ttl_s=60, now=NOW + 60), KEY, now=NOW) == "not_yet_valid"
    assert reason(verify, token, KEY, now=NOW + 62) == "expired"
