"""Approval tokens: HS256 JWTs the review service signs, bound to one tool call's exact input.

The review service mints them and the tool gateway's policy (OPA) verifies them with the same key; this module is the
token's shape, shared so neither service imports the other. Signing is HMAC today, where whoever can mint can also
verify, behind a Signer that an asymmetric KMS signer replaces so only the review service can mint.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, cast

from .tokens import HmacSigner, claims_of, verify
from .tokens import mint as _mint


@dataclass(frozen=True)
class Binding:
    """What an approval covers. `step` is the call's idempotency key, which survives a resume in a new process."""

    thread: str
    step: str
    tool: str
    inputHash: str  # noqa: N815 - the claim name is part of the wire contract with the policy
    approvers: list[str] = field(default_factory=list[str])


def mint_approval(binding: Binding, key: str, *, ttl_s: int, now: float | None = None) -> str:
    # The raw key, not a derived one: OPA verifies with the same key the gateway hands it at start.
    return _mint({**asdict(binding), "iss": "ops-review"}, HmacSigner(key.encode()), ttl_s=ttl_s, now=now)


def binding_of(token: str, key: str) -> Binding:
    """What a token this key signed covers, expired or not: the signature is checked, the expiry is not. For
    renewing an approval whose recorded approvals still stand (the caller's rule), never for authorising a call."""
    claims = verify(token, HmacSigner(key.encode()), now=float(claims_of(token).get("iat") or 0))
    return Binding(
        thread=str(claims["thread"]),
        step=str(claims["step"]),
        tool=str(claims["tool"]),
        inputHash=str(claims["inputHash"]),
        approvers=[str(a) for a in cast(list[Any], claims.get("approvers") or [])],
    )
