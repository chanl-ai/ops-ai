"""Meters every model call a graph makes and pauses the thread for a person when its budget is spent (E12).

A call is checked against the thread's budget before it runs and recorded after it returns. The model adapter reports
its usage through `report_usage`; the wrapper collects it, so call sites and test fakes stay unchanged. A fake that
reports nothing counts as one call with zero tokens."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast

from langgraph.config import get_config
from langgraph.types import interrupt

from ops_metering import Budget, Exhausted, Usage

from .models import Facts, Grade, GraphModels
from .usage import collecting, report_usage

__all__ = ["BudgetStoppedError", "CallSite", "Meter", "MeteredModels", "metered", "report_usage"]


@dataclass(frozen=True)
class CallSite:
    thread_id: str
    run_id: str | None
    node: str


class Meter(Protocol):
    async def exhausted(self, thread_id: str) -> Exhausted | None: ...
    async def update_budget(self, thread_id: str, budget: Budget) -> None: ...
    async def record(self, site: CallSite, kind: str, alias: str, usage: Usage) -> None: ...


class BudgetStoppedError(Exception):
    """A person rejected raising an exhausted budget; the run ends with this error."""


def call_site() -> CallSite | None:
    """Where the call runs, from LangGraph's run config; None outside a graph run."""
    try:
        cfg = get_config()
    except RuntimeError:
        return None
    configurable: Mapping[str, Any] = cfg.get("configurable", {})
    thread = configurable.get("thread_id")
    if not thread:
        return None
    run = configurable.get("run_id")
    node = cfg.get("metadata", {}).get("langgraph_node", "-")
    return CallSite(str(thread), str(run) if run else None, str(node))


def budget_from(raw: Mapping[str, Any]) -> Budget:
    """A budget from a request body or a resume decision, in either field style."""

    def pick(*names: str) -> Any:
        return next((raw[n] for n in names if raw.get(n) is not None), None)

    calls, tokens, cost = pick("max_calls", "maxCalls"), pick("max_tokens", "maxTokens"), pick("max_cost", "maxCost")
    return Budget(
        int(calls) if calls is not None else None,
        int(tokens) if tokens is not None else None,
        Decimal(str(cost)) if cost is not None else None,
    )


async def guard(meter: Meter, site: CallSite) -> None:
    """Pauses the thread while its budget is exhausted, through the same interrupt a human step uses. An approved
    decision carrying a `budget` raises the caps and the call goes ahead; a rejection stops the run. LangGraph restarts
    the node on resume, so calls the node made before this point run, and are recorded, again."""
    while (spent := await meter.exhausted(site.thread_id)) is not None:
        answer: Any = interrupt(
            {
                "kind": "budget_exhausted",
                "node": site.node,
                "limit": spent.limit,
                "spent": str(spent.spent),
                "cap": str(spent.cap),
                "needed": "Raise the budget to continue, or reject to stop this case.",
            }
        )
        decision = cast(dict[str, Any], answer) if isinstance(answer, dict) else {}
        if decision.get("decision") != "approved":
            raise BudgetStoppedError(f"Stopped at its {spent.limit} budget ({spent.spent} of {spent.cap}).")
        raw = decision.get("budget")
        if isinstance(raw, dict):
            await meter.update_budget(site.thread_id, budget_from(cast(dict[str, Any], raw)))


async def metered[T](
    meter: Meter | None, alias: str, kind: str, call: Callable[[], Awaitable[T]], *, record: bool = True
) -> T:
    """`record=False` checks the budget only: the kernel's model wrapper records each request of a kernel turn
    itself, with its latency and response (api/model_ledger.py)."""
    site = call_site()
    if meter is None or site is None:
        return await call()
    await guard(meter, site)
    if not record:
        return await call()
    with collecting() as got:
        try:
            return await call()
        finally:
            # Recorded even when the call raised: a provider call that failed after spending tokens was still paid
            # for, and a node that crashes and re-runs is counted once per attempt.
            usage = (
                Usage(sum(u.input_tokens for u in got), sum(u.output_tokens for u in got), sum(u.calls for u in got))
                if got
                else Usage()
            )
            await meter.record(site, kind, alias, usage)


class MeteredModels:
    """The workflow model calls, each checked against the budget and recorded."""

    def __init__(self, inner: GraphModels, meter: Meter | None, alias: str) -> None:
        self._inner, self._meter, self._alias = inner, meter, alias

    async def classify(self, text: str, labels: list[str]) -> str:
        return await metered(self._meter, self._alias, "classify", lambda: self._inner.classify(text, labels))

    async def extract(self, category: str, name: str, text: str) -> Facts:
        return await metered(self._meter, self._alias, "extract", lambda: self._inner.extract(category, name, text))

    async def draft(self, email: str, evidence: str, feedback: str | None) -> str:
        return await metered(self._meter, self._alias, "draft", lambda: self._inner.draft(email, evidence, feedback))

    async def grade(self, email: str, draft: str) -> Grade:
        return await metered(self._meter, self._alias, "grade", lambda: self._inner.grade(email, draft))

    async def extract_records(self, schema: str, text: str) -> list[dict[str, Any]]:
        return await metered(
            self._meter, self._alias, "extract_records", lambda: self._inner.extract_records(schema, text)
        )
