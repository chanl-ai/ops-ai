"""An operation's limits, checked the same way by the gateway (`/v1/calls`) and the console test panel, so the two
cannot disagree (c-028). The rate limit is spent at the gateway only (store/rate_windows.py); a test-panel call runs
nothing and spends nothing."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class Refusal:
    status: int
    code: str
    message: str


def amount_refusal(operation: dict[str, Any], args: dict[str, Any]) -> Refusal | None:
    """Why `args` break the operation's amount limit, or None. The limit applies to the operation's `amount` input:
    when the operation declares one, a call that leaves it out, sends a non-number or sends a negative amount is
    refused too, since a limit that a missing field or a sign flip skips is no limit. An operation that declares no
    `amount` input has nothing the limit can read; naming another field as the amount is a follow-up (c-028)."""
    if operation.get("amount_max") is None or not any(f.get("name") == "amount" for f in operation.get("input", [])):
        return None
    name, limit = operation["name"], Decimal(str(operation["amount_max"]))
    raw = args.get("amount")
    try:
        amount = None if isinstance(raw, bool) or raw in (None, "") else Decimal(str(raw))
    except InvalidOperation:
        amount = None
    if amount is None or not amount.is_finite():
        return Refusal(422, "invalid_input", f"{name} needs a numeric amount; its limit is {limit:f}")
    if amount < 0:
        # A cap compares upward only, so a negative amount would pass any limit and move money the other way.
        return Refusal(422, "invalid_input", f"{name} needs an amount of zero or more; got {amount:f}")
    if amount > limit:
        return Refusal(403, "amount_over_limit", f"amount {amount:f} is over {name}'s limit of {limit:f}")
    return None
