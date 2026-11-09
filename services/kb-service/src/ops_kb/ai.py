"""The model calls a split makes for a source's AI steps (likely questions), through models-service with kb-service's
own key (step `kb:questions`). The split is synchronous, so it runs in a worker thread on a blocking client.

One run (a sync or a rebuild) shares one client and one ceiling on model calls, and records what they spent on the run:
calls, input and output tokens, and why the step stopped if it did."""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from ops_ingest import ModelBudget, ModelUnavailable
from ops_service_kit.model_calls import IngestModel, ModelCallError

# The most model calls one run may make for its AI steps; past it the rest of its pieces get none, and the run says so.
MAX_CALLS_PER_RUN = 1_000
QUESTIONS_STEP = "kb:questions"


class AiClient(Protocol):
    """ops_ingest's ModelClient that also counts what it spent."""

    calls: int
    input_tokens: int
    output_tokens: int

    def complete(self, prompt: str, *, alias: str, max_tokens: int) -> str: ...


# A tenant's client for one run; None in a stack with no models-service, where an approved AI step adds nothing and the
# run says why.
AiClients = Callable[[str], AiClient]


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
            raise ModelUnavailable(e.code) from e
        finally:
            self.calls, self.input_tokens, self.output_tokens = (
                self.inner.calls,
                self.inner.input_tokens,
                self.inner.output_tokens,
            )


def models_clients(models_url: str, key: str) -> AiClients:
    def make(tenant: str) -> AiClient:
        http = httpx.Client(base_url=models_url, timeout=120)
        return ModelsIngest(IngestModel(http, key, tenant=tenant, step=QUESTIONS_STEP))

    return make


@dataclass
class AiRun:
    client: AiClient | None
    budget: ModelBudget = field(default_factory=lambda: ModelBudget(MAX_CALLS_PER_RUN))
    notes: set[str] = field(default_factory=set[str])

    def spend(self) -> dict[str, int]:
        c = self.client
        if c is None or not c.calls:
            return {}
        return {"modelCalls": c.calls, "inputTokens": c.input_tokens, "outputTokens": c.output_tokens}


CURRENT: ContextVar[AiRun | None] = ContextVar("kb_ai_run", default=None)


@contextmanager
def ai_run(clients: AiClients | None, tenant: str, *, fresh: bool = False) -> Generator[AiRun]:
    """One run's client and ceiling, for every split the run makes; a split inside a run shares it. `fresh` starts a
    run of its own (a rebuild, whose task may be made inside a sync)."""
    outer = None if fresh else CURRENT.get()
    if outer is not None:
        yield outer
        return
    run = AiRun(clients(tenant) if clients is not None else None)
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
