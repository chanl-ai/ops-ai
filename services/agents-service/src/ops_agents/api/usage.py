"""Model usage per call and budgets per thread (E12). Each metered call writes one row; totals and budget checks are
sums over those rows, done by the database, so no caller adds up costs itself.

Rows are written as each call returns, not at the checkpoint, so a call made by a node that later crashes is still
counted, and its re-run is counted again: both calls were paid for. Rows are not fenced by lease generation for the
same reason (E2b fences writes that change a case; spend is a fact either way).

Cost is stored as integer millionths of the currency unit so sums are exact on SQLite and PostgreSQL alike."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ops_metering import Budget, Totals


def budget_view(b: Budget | None) -> dict[str, Any] | None:
    if b is None:
        return None
    return {
        "maxCalls": b.max_calls,
        "maxTokens": b.max_tokens,
        "maxCost": str(b.max_cost) if b.max_cost is not None else None,
    }


def totals_view(t: Totals) -> dict[str, Any]:
    return {
        "calls": t.calls,
        "inputTokens": t.input_tokens,
        "outputTokens": t.output_tokens,
        "cost": str(t.cost),
    }


@dataclass(frozen=True)
class Refusal:
    reason: str


class KeyAdmission(Protocol):
    """Whether the calling key may open a new thread. The per-key ledger belongs to the models service; until it
    exists the agents service asks this port, and the default admits every key."""

    async def admit(self, key_id: str) -> Refusal | None: ...


class AdmitAll:
    async def admit(self, key_id: str) -> Refusal | None:
        return None
