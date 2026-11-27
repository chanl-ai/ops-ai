"""The budgets a conversation or a workflow step spends from, kept by the model gateway (models-service), and the
headers every model call names them with (docs/design/agents-v2/model-gateway.md, "Budgets").

The gateway reserves each call against the budgets it names before the provider is called, records the answer under
the call's replay key, and answers a repeat of the same request under that key from the record without charging it
again. This module creates and updates a budget (`PUT /v1/models/budgets/{id}`), reads its spend back for the budget
card, and wraps the kernel's model so each request carries:

| Header | Chat turn | Workflow step |
|---|---|---|
| `X-Budget-Id` | `thread:<id>` of the chain's first thread, when it has one | `step:<run>:<node>`, when set |
| `X-Replay-Key` | `turn:<thread>:<task>` | `run:<run>:<node>:<iteration>` |
| `X-Call-Purpose` | set by the kernel per call: `turn`, `closing`, `check`, `judge` | the same |

A refused call (429 `budget_reached` or `check_cap_reached`) raises the kernel's `BudgetReachedError`. Only the thread
the chain started on makes the reply's closing call: a specialist's closing call is refused here, before it is sent,
because the gateway would admit one closing call under the specialist's own replay key.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx
from langgraph.config import get_config
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters, StreamedResponse
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.settings import ModelSettings

from ops_agent_kernel.ports import PURPOSE_HEADER, BudgetReachedError, ModelSource
from ops_agents.graphs.common import emit
from ops_agents.graphs.metering import STEP_KEY, call_site
from ops_identity import ServiceCallError, ServiceClient
from ops_metering import Budget, Exhausted, Totals
from ops_service_kit.http import Json
from ops_service_kit.ids import new_id
from ops_service_kit.settings import Settings
from ops_store import isolation

from ..store.chains import ChainStore
from ..store.tenancy import current_tenant

BUDGET_HEADER = "X-Budget-Id"
REPLAY_HEADER = "X-Replay-Key"
# The gateway's refusals that end a reply; any other error is the call's own failure.
REFUSED = frozenset({"budget_reached", "check_cap_reached"})
CREATED_BY = "agents:api/budgets.py"
# Pages of the call log read for one thread's spend per run; a thread past this many pages reports what it read.
MAX_CALL_PAGES = 50


def _int(value: object) -> int:
    return int(str(value or 0))


def thread_budget(thread_id: str) -> str:
    return f"thread:{thread_id}"


def step_budget(run_id: str, node: str) -> str:
    return f"step:{run_id}:{node}"


# The budget a workflow step's calls name, set by the agent step for the length of its turn (api/engine_agents.py).
STEP_BUDGET: ContextVar[str | None] = ContextVar("ops_agents_step_budget", default=None)


@contextmanager
def spending_from(budget_id: str | None) -> Generator[None]:
    token = STEP_BUDGET.set(budget_id)
    try:
        yield
    finally:
        STEP_BUDGET.reset(token)


def _caps(budget: Budget) -> Json:
    return {
        "maxCalls": budget.max_calls,
        "maxTokens": budget.max_tokens,
        "maxCostUsd": str(budget.max_cost) if budget.max_cost is not None else None,
    }


def _budget_of(row: Json) -> Budget:
    cost = row.get("maxCostUsd")
    return Budget(
        cast(int | None, row.get("maxCalls")),
        cast(int | None, row.get("maxTokens")),
        Decimal(str(cost)) if cost is not None else None,
    )


class GatewayBudgets:
    """The thread budgets of this tenant on the model gateway, through a service token with `models:budgets`; the
    graph meter (graphs/metering.py `Meter`) and the chat's budget card read and write them here."""

    def __init__(self, models: ServiceClient, chains: ChainStore) -> None:
        self.models = models
        self.chains = chains
        # Budgets known to exist, so a call asks the gateway once per thread whether to name one. Only a yes is kept:
        # a budget is never deleted while its thread runs.
        self.known: set[str] = set()

    async def _row(self, budget_id: str) -> Json | None:
        # The gateway holds budgets per tenant; a team reads only its own, as the ledger rows were team-scoped. Read
        # before the call: an in-process gateway (tests) enters its own caller's scope on this task.
        team = isolation.team()
        try:
            row = cast(Json, await self.models.get(f"/v1/models/budgets/{budget_id}"))
        except ServiceCallError as e:
            if e.status == 404:
                return None
            raise
        self.known.add(budget_id)
        if team is not None and row.get("teamId") not in (None, team):
            return None
        return row

    async def put(self, budget_id: str, kind: str, team_id: str, budget: Budget, *, parent: str | None = None) -> None:
        body: Json = {"kind": kind, "teamId": team_id, "createdBy": CREATED_BY, "parentId": parent, **_caps(budget)}
        await self.models.request("PUT", f"/v1/models/budgets/{budget_id}", json=body)
        self.known.add(budget_id)

    async def budget(self, thread_id: str) -> Budget | None:
        row = await self._row(thread_budget(thread_id))
        return _budget_of(row) if row is not None else None

    async def set_budget(self, thread_id: str, budget: Budget) -> None:
        team = await self.chains.team_of(thread_id) or isolation.team()
        if team is None:
            raise LookupError(f"Thread {thread_id} has no team to hold its budget.")
        await self.put(thread_budget(thread_id), "thread", team, budget)

    async def update_budget(self, thread_id: str, budget: Budget) -> None:
        current = await self.budget(thread_id) or Budget()
        await self.set_budget(thread_id, current.updated(budget))

    async def totals(self, thread_id: str) -> Totals:
        """What the thread's chain has spent: every call that named its budget, its specialists' included. The
        gateway keeps one token total, shown as input tokens."""
        row = await self._row(thread_budget(thread_id))
        if row is None:
            return Totals()
        cost = Decimal(str(row.get("spentCostUsd") or 0))
        return Totals(_int(row.get("spentCalls")), _int(row.get("spentTokens")), 0, cost)

    async def exhausted(self, thread_id: str) -> Exhausted | None:
        row = await self._row(thread_budget(thread_id))
        limit = row.get("exhausted") if row is not None else None
        if row is None or limit is None:
            return None
        spent: dict[str, int | Decimal] = {
            "calls": _int(row.get("spentCalls")),
            "tokens": _int(row.get("spentTokens")),
            "cost": Decimal(str(row.get("spentCostUsd") or 0)),
        }
        caps = {"calls": row.get("maxCalls"), "tokens": row.get("maxTokens"), "cost": row.get("maxCostUsd")}
        cap = caps[str(limit)]
        return Exhausted(
            cast(Any, limit), spent[str(limit)], Decimal(str(cap)) if limit == "cost" else int(str(cap or 0))
        )

    async def totals_by_run(self, thread_id: str) -> dict[str | None, Totals]:
        """The thread's own answered calls summed per run, from the gateway's call log: a refused call cost nothing
        and a replayed one was paid for once already."""
        sums: dict[str | None, Totals] = {}
        for page in range(1, MAX_CALL_PAGES + 1):
            params = {"threadId": thread_id, "outcome": "ok", "page": page}
            body = cast(Json, await self.models.get("/v1/models/calls", params=params))
            for c in cast(list[Json], body.get("data") or []):
                run = cast(str | None, c.get("runId"))
                was = sums.get(run, Totals())
                sums[run] = Totals(
                    was.calls + 1,
                    was.input_tokens + _int(c.get("inputTokens")),
                    was.output_tokens + _int(c.get("outputTokens")),
                    was.cost + Decimal(str(c.get("cost") or 0)),
                )
            if not cast(Json, body.get("pagination") or {}).get("hasNext"):
                break
        return sums

    async def named(self, thread_id: str) -> str | None:
        """The budget a call on `thread_id` names: the thread its chain started on, when that thread has one."""
        root = await self.chains.chain_root(thread_id)
        budget_id = thread_budget(root)
        if budget_id in self.known or await self._row(budget_id) is not None:
            return budget_id
        return None

    async def chain_root(self, thread_id: str) -> str:
        return await self.chains.chain_root(thread_id)


@dataclass(frozen=True)
class _Site:
    thread_id: str | None
    run_id: str | None
    node: str
    replay_key: str


def _site() -> _Site | None:
    """Where the request runs and the key its re-run repeats: a graph run's thread and task (a chat turn's own key
    when it set one), or a workflow step's id outside a graph run. None for a call that is neither."""
    call, key = call_site(), STEP_KEY.get()
    if call is None:
        if key is None:
            return None
        run, node = key.rsplit(":", 2)[:2] if key.count(":") >= 2 else (key, "-")
        return _Site(None, run or None, node, f"run:{key}")
    task = key
    if task is None:
        cfg = get_config()
        found = (cfg.get("configurable") or {}).get("checkpoint_ns") or (cfg.get("metadata") or {}).get(
            "langgraph_checkpoint_ns"
        )
        # A call with no task still names its budget; its key is its own, so it is never replayed.
        task = str(found) if found else new_id("task")
    return _Site(call.thread_id, call.run_id, call.node, f"turn:{call.thread_id}:{task}")


def _purpose(settings: ModelSettings | None) -> str:
    return str(((settings or {}).get("extra_headers") or {}).get(PURPOSE_HEADER) or "turn")


def _refused(e: ModelHTTPError) -> bool:
    raw: object = e.body
    if e.status_code != 429 or not isinstance(raw, dict):
        return False
    body = cast(Json, raw)
    error = body.get("error")
    code = cast(Json, error).get("code") if isinstance(error, dict) else body.get("code")
    return code in REFUSED


def gateway_budgets(settings: Settings, http: httpx.AsyncClient, db: Any) -> GatewayBudgets | None:
    """The tenant's budgets on models-service, or None when this process has no service signing key to ask with."""
    try:
        client = ServiceClient.for_settings(
            settings, http, service="agents", audience="models", scopes=["models:budgets"],
            tenant=current_tenant, team=_no_team,
        )  # fmt: skip
    except ValueError:
        return None
    return GatewayBudgets(client, ChainStore(db))


def _no_team() -> str | None:
    return None


class BudgetedModel(WrapperModel):
    """The kernel's model with each request naming its tenant, its budget and its replay key. `headers` is False for
    a model that calls a provider directly, which is never sent them; its calls are then reported only, and no budget
    holds. With no `budgets` a request names no budget."""

    def __init__(self, wrapped: Model, budgets: GatewayBudgets | None, alias: str, *, headers: bool = True) -> None:
        super().__init__(wrapped)
        self.budgets = budgets
        self.alias = alias
        self.headers = headers

    async def _headed(self, settings: ModelSettings | None, site: _Site | None) -> ModelSettings | None:
        if not self.headers:
            return settings
        headers: dict[str, str] = {}
        with contextlib.suppress(isolation.NoTenantError):
            headers["X-Tenant-Id"] = isolation.tenant()
        budget_id: str | None = None
        if site is not None:
            headers[REPLAY_HEADER] = site.replay_key
            headers["X-Step-Id"] = site.node
            if site.run_id:
                headers["X-Run-Id"] = site.run_id
            if site.thread_id is not None:
                headers["X-Thread-Id"] = site.thread_id
                if self.budgets is not None:
                    if _purpose(settings) == "closing" and await self.budgets.chain_root(site.thread_id) != (
                        site.thread_id
                    ):
                        # A specialist returns what it has to the agent that asked it; only the chain's first thread
                        # closes the reply.
                        raise BudgetReachedError()
                    budget_id = await self.budgets.named(site.thread_id)
            else:
                budget_id = STEP_BUDGET.get()
        if budget_id is not None:
            headers[BUDGET_HEADER] = budget_id
        if not headers:
            return settings
        merged: ModelSettings = {**(settings or {})}
        merged["extra_headers"] = {**(merged.get("extra_headers") or {}), **headers}
        return merged

    def _emit(self, site: _Site | None, response: ModelResponse, started: float) -> None:
        if site is None or site.thread_id is None:
            return
        u = response.usage
        emit(
            "model_call",
            site.node,
            {
                "alias": self.alias,
                "inputTokens": u.input_tokens,
                "outputTokens": u.output_tokens,
                "latencyMs": int((time.perf_counter() - started) * 1000),
            },
        )

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        site = _site()
        settings = await self._headed(model_settings, site)
        started = time.perf_counter()
        try:
            response = await super().request(messages, settings, model_request_parameters)
        except ModelHTTPError as e:
            if _refused(e):
                raise BudgetReachedError() from e
            raise
        self._emit(site, response, started)
        return response

    @asynccontextmanager
    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any = None,
    ) -> AsyncGenerator[StreamedResponse]:
        site = _site()
        settings = await self._headed(model_settings, site)
        started = time.perf_counter()
        try:
            async with self.wrapped.request_stream(messages, settings, model_request_parameters, run_context) as s:
                yield s
        except ModelHTTPError as e:
            if _refused(e):
                raise BudgetReachedError() from e
            raise
        self._emit(site, s.get(), started)


class BudgetedSource:
    """Each alias's model wrapped once in `BudgetedModel`."""

    def __init__(self, models: ModelSource, budgets: GatewayBudgets | None) -> None:
        self.source = models
        self.budgets = budgets
        self.models: dict[str, Model] = {}

    def model_for(self, alias: str) -> Model:
        if alias not in self.models:
            self.models[alias] = BudgetedModel(self.source.model_for(alias), self.budgets, alias)
        return self.models[alias]


__all__ = [
    "BUDGET_HEADER",
    "REPLAY_HEADER",
    "STEP_BUDGET",
    "BudgetedModel",
    "BudgetedSource",
    "GatewayBudgets",
    "gateway_budgets",
    "spending_from",
    "step_budget",
    "thread_budget",
]
