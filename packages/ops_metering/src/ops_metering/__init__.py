"""Usage accounting shared by every service that meters model calls: the agents service (thread budgets) and the
models service (key ledgers). Arithmetic only; callers own storage and the rule for what happens at a cap.

Money is `Decimal` rounded to millionths of the currency unit, so totals summed in any order agree to the cent."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

MICRO = Decimal("0.000001")
MILLION = Decimal(1_000_000)
ZERO = Decimal(0)

Limit = Literal["calls", "tokens", "cost"]


@dataclass(frozen=True)
class Price:
    """Price per million tokens, in the deployment's currency."""

    input_per_million: Decimal = ZERO
    output_per_million: Decimal = ZERO


class PriceTable:
    """Prices by model alias. An alias with no entry costs zero, so a scripted or self-hosted model meters tokens
    without inventing a price; `priced` tells the two cases apart."""

    def __init__(self, prices: Mapping[str, Price] | None = None) -> None:
        self._prices = dict(prices or {})

    @classmethod
    def parse(cls, raw: Mapping[str, Mapping[str, str | float | int]]) -> PriceTable:
        """From settings: `{"gpt-5.5": {"input": "1.25", "output": "10"}}`, per million tokens."""
        return cls(
            {
                alias: Price(Decimal(str(p.get("input", 0))), Decimal(str(p.get("output", 0))))
                for alias, p in raw.items()
            }
        )

    def price(self, alias: str) -> Price:
        return self._prices.get(alias, Price())

    def priced(self, alias: str) -> bool:
        return alias in self._prices


@dataclass(frozen=True)
class Usage:
    """One model call's usage. `calls` is the number of provider requests it made (a tool loop makes several)."""

    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 1

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def cost(usage: Usage, price: Price) -> Decimal:
    raw = (usage.input_tokens * price.input_per_million + usage.output_tokens * price.output_per_million) / MILLION
    return raw.quantize(MICRO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost: Decimal = ZERO

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, usage: Usage, amount: Decimal) -> Totals:
        return Totals(
            self.calls + usage.calls,
            self.input_tokens + usage.input_tokens,
            self.output_tokens + usage.output_tokens,
            self.cost + amount,
        )


def total(rows: Iterable[tuple[Usage, Decimal]]) -> Totals:
    out = Totals()
    for usage, amount in rows:
        out = out.add(usage, amount)
    return out


@dataclass(frozen=True)
class Budget:
    """Caps on calls, tokens and cost; an unset cap does not limit."""

    max_calls: int | None = None
    max_tokens: int | None = None
    max_cost: Decimal | None = None

    def is_empty(self) -> bool:
        return self.max_calls is None and self.max_tokens is None and self.max_cost is None

    def updated(self, other: Budget) -> Budget:
        """`other`'s caps where set, this budget's elsewhere: how a person raises one cap without clearing the rest."""
        return Budget(
            other.max_calls if other.max_calls is not None else self.max_calls,
            other.max_tokens if other.max_tokens is not None else self.max_tokens,
            other.max_cost if other.max_cost is not None else self.max_cost,
        )


@dataclass(frozen=True)
class Exhausted:
    limit: Limit
    spent: int | Decimal
    cap: int | Decimal


def exhausted(totals: Totals, budget: Budget) -> Exhausted | None:
    """The first cap already reached, or None. Checked before a call, so the call that crosses a cap still completes:
    spend can pass a cap by at most one call."""
    if budget.max_calls is not None and totals.calls >= budget.max_calls:
        return Exhausted("calls", totals.calls, budget.max_calls)
    if budget.max_tokens is not None and totals.tokens >= budget.max_tokens:
        return Exhausted("tokens", totals.tokens, budget.max_tokens)
    if budget.max_cost is not None and totals.cost >= budget.max_cost:
        return Exhausted("cost", totals.cost, budget.max_cost)
    return None
