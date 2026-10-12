"""Step-up tokens: proof that a named person re-authenticated recently.

Minted by the sign-in path right after a re-authentication, and checked wherever a decision needs one. The check is
signature, type, subject and age; which decisions need a step-up is the caller's rule, not this module's.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .tokens import Signer, TokenError, mint, verify

STEP_UP_TYPE = "step_up"
# A step-up proves a re-authentication within this window (spec 13: five minutes).
STEP_UP_TTL_S = 300


@dataclass(frozen=True)
class StepUp:
    subject: str
    issued_at: int


def mint_step_up(subject: str, signer: Signer, *, now: float | None = None, ttl_s: int = STEP_UP_TTL_S) -> str:
    return mint({"sub": subject, "typ": STEP_UP_TYPE}, signer, ttl_s=ttl_s, now=now)


def verify_step_up(
    token: str, subject: str, signer: Signer, *, now: float | None = None, max_age_s: int = STEP_UP_TTL_S
) -> StepUp:
    """The step-up if `token` was minted by `signer` for `subject` within `max_age_s`; raises TokenError otherwise."""
    claims = verify(token, signer, now=now)
    if claims.get("typ") != STEP_UP_TYPE:
        raise TokenError("type", "That token is not a step-up token.")
    if claims.get("sub") != subject:
        raise TokenError("subject", "The step-up was made by someone else.")
    issued = int(claims["iat"])
    age = (now if now is not None else time.time()) - issued
    if age > max_age_s:
        # Separate from `exp`: a caller may want a shorter window than the token was minted with.
        raise TokenError("too_old", f"The step-up is older than {max_age_s // 60} minutes; re-authenticate.")
    return StepUp(subject=subject, issued_at=issued)
