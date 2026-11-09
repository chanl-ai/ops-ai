"""The model calls a split makes for a source's AI steps (likely questions), through models-service with kb-service's
own key (step `kb:questions`). The split is synchronous, so it runs in a worker thread on a blocking client.

One run (a sync or a rebuild) shares one client, named to models-service by the run's own id with the source's ceiling
in money (its `aiCeiling`, $5 by default): models-service refuses a call once what it recorded for the run reaches it,
and refuses every call of kb-service's key past the environment's daily cap. The run records what the calls spent
(calls, input and output tokens) and why the step stopped if it did."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ops_ingest import ModelBudgetSpent, ModelUnavailable
from ops_service_kit.ids import new_id
from ops_service_kit.model_calls import IngestModel, ModelCallError

QUESTIONS_STEP = "kb:questions"
# models-service's refusals that mean a spend ceiling, which stop the step as a ceiling rather than an outage.
CEILINGS = {
    "run_spend_cap": "this sync reached its source's ceiling",
    "daily_spend_cap": "today's ceiling for the environment",
}


class AiClient(Protocol):
    """ops_ingest's ModelClient that also counts what it spent."""

    calls: int
    input_tokens: int
    output_tokens: int

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str: ...


# A client for one tenant's run, by (tenant, run id, the run's ceiling in money); None in a stack with no
# models-service, where an approved AI step adds nothing and the run says why.
AiClients = Callable[[str, str, float], AiClient]


@dataclass
class ModelsIngest:
    """IngestModel on models-service, its refusals as ops_ingest's ModelUnavailable so the split stops asking."""

    inner: IngestModel
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str:
        try:
            return self.inner.complete(prompt, alias=alias, max_tokens=max_tokens)
        except ModelCallError as e:
            if e.code in CEILINGS:
                raise ModelBudgetSpent(CEILINGS[e.code]) from e
            raise ModelUnavailable(e.code) from e
        finally:
            self.calls, self.input_tokens, self.output_tokens = (
                self.inner.calls,
                self.inner.input_tokens,
                self.inner.output_tokens,
            )


def models_clients(models_url: str, key: str) -> AiClients:
    def make(tenant: str, run_id: str, ceiling: float) -> AiClient:
        http = httpx.Client(base_url=models_url, timeout=120)
        inner = IngestModel(http, key, tenant=tenant, step=QUESTIONS_STEP, run_id=run_id, run_cap=f"{ceiling:.2f}")
        return ModelsIngest(inner)

    return make


@dataclass
class AiRun:
    client: AiClient | None
    notes: set[str] = field(default_factory=set[str])

    def spend(self) -> dict[str, int]:
        c = self.client
        if c is None or not c.calls:
            return {}
        return {"modelCalls": c.calls, "inputTokens": c.input_tokens, "outputTokens": c.output_tokens}


CURRENT: ContextVar[AiRun | None] = ContextVar("kb_ai_run", default=None)


@contextmanager
def ai_run(clients: AiClients | None, tenant: str, *, ceiling: float, fresh: bool = False) -> Generator[AiRun]:
    """One run's client and ceiling, for every split the run makes; a split inside a run shares it. `fresh` starts a
    run of its own (a rebuild, whose task may be made inside a sync)."""
    outer = None if fresh else CURRENT.get()
    if outer is not None:
        yield outer
        return
    run = AiRun(clients(tenant, new_id("airun"), ceiling) if clients is not None else None)
    token = CURRENT.set(run)
    try:
        yield run
    finally:
        CURRENT.reset(token)


def spent_on(counts: dict[str, Any], log: list[str]) -> None:
    """The current run's model spend into its counts, and why its AI step stopped into its log."""
    run = CURRENT.get()
    if run is None:
        return
    counts.update(run.spend())
    log.extend(sorted(run.notes))
