"""agents-service as the workflow runner's host: the adapters behind ops_engine's ports, and the worker they make up.

| Port | Adapter here | Backed by |
|---|---|---|
| ToolPort | GatewayTools | tools-service `POST /v1/calls`, `GET /v1/tools/{name}`, `GET /v1/executions?key=` |
| ReviewPort | RunReviews | engine_runs.waiting, which the Reviews facade lists (api/engine_reviews.py) |
| LeasePort | ThreadLeases | thread_leases (store/leases.py), the same lease and generation v1 runs take |
| EventPort | RunEvents | thread_events, so GET /v1/runs/{id}/events re-attaches with after=seq |

A run's thread id is its run id (RUN_PREFIX), so its lease, checkpoints and events never meet a v1 thread's.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, cast

from ops_agents.activities.gateway import (
    RUN_CONTEXT,
    GatewayClient,
    GatewayRefused,
    RunContext,
    current_run_context,
    gateway_error,
)
from ops_checkpointer import LeaseSupersededError
from ops_engine.ports import AS_TEAM_ACCOUNT, STEP_ACCOUNTS, Access, LeaseBusyError, ToolResult
from ops_engine.store import DefinitionStore, RunStore
from ops_identity import ServiceCallError
from ops_policy import input_hash
from ops_policy.approval import Binding, mint_approval
from ops_service_kit.logging import get_logger

from ..domain.accounts import chosen_accounts
from ..store.engine import AsyncEngine, EngineTransactions
from ..store.events import EventLog
from ..store.leases import LeaseHeldError, Leases
from ..store.reviews import ReviewStore
from .engine_agents import KernelAgents
from .event_workflows import EVENT_WORKFLOWS, handlers
from .platform_policies import PolicySource, PolicyUnread
from .task_assist import TaskAssist, kernel_assist

log = get_logger("ops_agents.api.engine_host")


class NoGatewayError(RuntimeError):
    pass


def thread_of(key: str) -> str:
    """A tool key is run:node:iteration:attempt, and the run id is the thread id."""
    return key.split(":", 1)[0]


@dataclass(frozen=True)
class ApprovalMinter:
    """Mints a review-approved write's token in the worker, at the call, from the approvals recorded for that exact
    input (as ApprovalRenewal does for v1), so no token is ever stored."""

    db: AsyncEngine
    review_key: str
    ttl_s: int

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        digest = input_hash(call["input"])
        raw: list[Any] = list(approval.get("approvers") or [])
        step, approvers = str(call["step"]), [str(a) for a in raw]
        if digest != approval.get("inputHash") or step != approval.get("step") or not approvers:
            return None  # the call is not the one approved
        rows = await ReviewStore(self.db).approvals_of_input(run_id, step, digest)
        if not set(approvers) <= {a for a, _ in rows}:
            return None  # an approval was withdrawn or replaced by one of a different input
        workflow, system = await run_workflow(self.db, run_id)
        binding = Binding(run_id, step, str(call["tool"]), digest, approvers, workflow=workflow, system=system)
        return mint_approval(binding, self.review_key, ttl_s=self.ttl_s)


async def run_workflow(db: AsyncEngine, run_id: str) -> tuple[str, bool]:
    """The run's workflow id, and whether it is the tenant's handler for a service event (the approval's `system`
    claim): the no-team workflow under a shipped event workflow's id. tools-service lets only the access
    request's handler apply a tool access decision."""
    tx = EngineTransactions(db)
    run = await RunStore(tx).get(run_id)
    if run is None:
        return "", False
    workflow = str(run["workflow_id"])
    stored = await DefinitionStore(tx).get(workflow, int(run["version"]))
    handler = workflow in set(handlers(EVENT_WORKFLOWS).values())
    return workflow, bool(handler and stored is not None and stored.get("team_id") is None)


class GatewayTools:
    def __init__(self, gateway: GatewayClient | None, minter: ApprovalMinter | None = None) -> None:
        self.gateway = gateway
        self.minter = minter

    async def mint(self, run_id: str, call: dict[str, Any], approval: dict[str, Any]) -> str | None:
        return await self.minter.mint(run_id, call, approval) if self.minter is not None else None

    def _gw(self) -> GatewayClient:
        if self.gateway is None:
            raise NoGatewayError("no tool gateway is configured (OPS_GATEWAY_URL)")
        return self.gateway

    async def call(
        self,
        operation: str,
        input: dict[str, Any],
        key: str,
        generation: int | None,
        token: str | None,
    ) -> ToolResult:
        # The gateway fences writes on the run's lease generation and logs the call against the run's thread.
        # The run's mode, from the graph's config, picks the connection environment its calls use.
        run = current_run_context()
        team_account = AS_TEAM_ACCOUNT.get()
        ctx = RUN_CONTEXT.set(
            RunContext(
                thread=thread_of(key),
                act="graph",
                generation=generation,
                environment=run.environment,
                run_id=run.run_id,
                team_account=team_account,
                # The run's accounts are the choice of the chat or agent that started it; the step's wins.
                accounts=chosen_accounts(agent=run.accounts, step=STEP_ACCOUNTS.get(), team_account=team_account),
            )
        )
        try:
            data = await self._gw().call(operation, input, key=key, approval_token=token)
        except GatewayRefused as e:
            # The gateway's own codes for a write under a key it already holds, read for what they say:
            # still running is pending, an abandoned key never ran, and a newer lease owns the run now.
            if e.code == "write_in_progress":
                return ToolResult(False, pending=True, reason=str(e))
            if e.code == "call_abandoned":
                return ToolResult(False, not_sent=True, reason=str(e))
            if e.code == "lease_superseded":
                raise LeaseSupersededError(str(e)) from e
            return ToolResult(False, refused=True, reason=str(e))
        except ServiceCallError as e:
            if e.status >= 500:
                raise  # no answer from the operation: the wrapper retries a read, and a write takes the error port
            return ToolResult(False, output=gateway_error(e), reason=str(e) or f"the gateway answered {e.status}")
        finally:
            RUN_CONTEXT.reset(ctx)
        ok = bool(data.get("ok"))
        return ToolResult(ok, data.get("output"), reason=None if ok else said(data.get("output")))

    async def access(self, operation: str) -> Access:
        found = await self._gw().tool_access(operation)
        return found if found in ("read", "write") else "unknown"

    async def deadline(self, operation: str) -> float | None:
        """How long the gateway may take over one call of `operation`; the step waits at least that long."""
        found = (await self._gw().tool_policy(operation)).get("deadlineSeconds")
        return float(found) if isinstance(found, (int, float)) else None

    async def find(self, key: str, operation: str) -> ToolResult | None:
        """The gateway's record of the write sent under `key`, decided on its claim (the effect row) alone; with no
        record the gateway abandons the key, so the call cannot run if it is still in flight. The log keeps no output,
        so a write found done is recorded with its call id."""
        found = await self._gw().abandon(key, operation, thread_of(key))
        call: dict[str, Any] | None = found.get("call")
        if found.get("abandoned") or call is None:
            return None
        outcome = str(call.get("outcome") or "")
        if call.get("effect"):
            if outcome == "running":
                return ToolResult(False, pending=True, reason="the gateway is still running the call")
            if outcome in ("ok", "replayed"):
                return ToolResult(True, {"reconciled": True, "callId": call["id"], "status": outcome})
            reason = "the gateway lost the call; it may have run" if outcome == "lost" else "the call failed"
            output = {"callId": call["id"], "error": call.get("error")}
            return ToolResult(False, output, reason=reason, lost=outcome == "lost")
        if outcome == "refused":
            return ToolResult(False, refused=True, reason="the gateway refused the call")
        return None  # no claim: the write never ran


def said(output: Any) -> str:
    """A failed operation's own message, which a run's failure reads (worker._why_failed): it names the app and what to
    do, as "Client desk needs reconnecting" does."""
    error = cast(dict[str, Any], output).get("error") if isinstance(output, dict) else None
    message = cast(dict[str, Any], error).get("message") if isinstance(error, dict) else None
    return str(message) if message else "the operation returned an error"


class GatewayExpressions:
    """Calculate steps' formulas, evaluated by the tool gateway as the run's tenant."""

    def __init__(self, gateway: GatewayClient) -> None:
        self.gateway = gateway

    async def evaluate(
        self, expressions: dict[str, str], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        return await self.gateway.evaluate(expressions, values)


class StarterApprovals:
    """A review step approving one write, decided as the run starter's own when they may approve it: the run recorded at
    its start that they hold reviews.decide under the four-eyes policy. Only
    a write one person approves without a step-up qualifies, the operation's policy and the workspace's stepUp read
    live; anything unread leaves the step waiting for a person. The approval is recorded as the starter's, so the
    tool node mints its token from it as from any decision."""

    def __init__(self, db: AsyncEngine, gateway: GatewayClient | None, policies: PolicySource | None = None) -> None:
        self.db = db
        self.gateway = gateway
        self.policies = policies

    async def decision(self, run_id: str, node_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        run = await RunStore(EngineTransactions(self.db)).get(run_id)
        if run is None or not run.get("started_by_approver") or self.gateway is None:
            return None
        call = dict(payload["call"])
        tool = str(call["tool"])
        try:
            approval = dict((await self.gateway.tool_policy(tool)).get("approval") or {})
            stepped = bool(await self.policies.value("stepUp")) if self.policies is not None else False
        except (ServiceCallError, PolicyUnread, KeyError, TypeError, ValueError):
            return None
        if stepped or approval.get("stepUp") or int(approval.get("approvers") or 1) > 1:
            return None
        starter, digest = str(run["created_by"]), input_hash(call["input"])
        found = await ReviewStore(self.db).approve(
            run_id, str(call["step"]), starter, digest, distinct=False, team_id=str(run["team_id"])
        )
        if not found:
            return None
        await EventLog(self.db).append(
            thread_id=run_id,
            team_id=str(run["team_id"]),
            run_id=run_id,
            type_="decided",
            node=node_id,
            data={"decision": "approved", "option": None, "decidedBy": starter, "own": True},
        )
        return {
            "decision": "approved",
            "by": starter,
            "call": call,
            "approval": {"step": str(call["step"]), "tool": tool, "inputHash": digest, "approvers": found},
        }


class RunReviews:
    """A review step's review is its run: the worker records the waiting step on the run when the graph pauses, and
    Reviews lists it from there. Opening is therefore idempotent by construction. With `assist`, a typed step's task
    gets its task assist once, in the run's team: recorded as pending at the pause, and written by the model
    call beside the pause rather than in it, since that call can take seconds and the task is shown and decided
    without it."""

    def __init__(
        self,
        assist: TaskAssist | None = None,
        tx: EngineTransactions | None = None,
        starters: StarterApprovals | None = None,
    ) -> None:
        self.assist = assist
        self.tx = tx
        self.starters = starters
        # Held so a running assist is not collected before it ends.
        self._writing: set[asyncio.Task[None]] = set()

    async def open(self, run_id: str, node_id: str, iteration: int, payload: dict[str, Any]) -> str:
        if self.assist is not None and self.tx is not None and payload.get("taskType"):
            run = await RunStore(self.tx).get(run_id)
            if run is not None:
                request = await self.assist.start(str(run["team_id"]), payload)
                if request is not None:
                    task = asyncio.create_task(self.assist.finish(str(payload["step_id"]), request))
                    self._writing.add(task)
                    task.add_done_callback(self._done)
        return run_id

    async def own_decision(self, run_id: str, node_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        return await self.starters.decision(run_id, node_id, payload) if self.starters is not None else None

    def _done(self, task: asyncio.Task[None]) -> None:
        self._writing.discard(task)
        if not task.cancelled() and (e := task.exception()) is not None:
            log.warning("task_assist_crashed", error=type(e).__name__)

    async def settled(self) -> None:
        """Waits for the assists being written (a worker stopping, a test reading them)."""
        if self._writing:
            await asyncio.gather(*self._writing, return_exceptions=True)


def assisted_reviews(
    stack: AsyncExitStack,
    db: AsyncEngine,
    agents: KernelAgents,
    policies: PolicySource,
    starters: StarterApprovals | None = None,
) -> RunReviews:
    """The worker's reviews port with task assist. Closing `stack` (the worker stopping) waits for the assists
    still being written, so one is not lost mid-call and its task does not stay pending."""
    reviews = RunReviews(kernel_assist(db, agents, policies), EngineTransactions(db), starters)
    stack.push_async_callback(reviews.settled)
    return reviews


class ThreadLeases:
    def __init__(self, leases: Leases) -> None:
        self.leases = leases
        self.ttl = leases.ttl

    async def acquire(self, thread_id: str, run_id: str) -> int:
        try:
            return await self.leases.acquire(thread_id, run_id)
        except LeaseHeldError as e:
            raise LeaseBusyError(str(e)) from e

    async def heartbeat(self, thread_id: str, run_id: str) -> bool:
        return await self.leases.heartbeat(thread_id, run_id)

    async def release(self, thread_id: str, run_id: str) -> None:
        await self.leases.release(thread_id, run_id)


class RunEvents:
    def __init__(self, log_: EventLog) -> None:
        self.log = log_

    async def append(
        self, run_id: str, team_id: str, type_: str, node: str | None, data: Any, *, generation: int | None = None
    ) -> None:
        await self.log.append(
            thread_id=run_id, team_id=team_id, run_id=run_id, type_=type_, node=node, data=data, generation=generation
        )


class KillAfterNode:
    """uc-081's fault: SIGKILL to this process once the named node's step row is recorded, before LangGraph saves the
    step, which is the window the recorded-output lookup exists for."""

    def __init__(self, node: str) -> None:
        self.node = node

    async def after_step(self, run_id: str, node_id: str, status: str) -> None:
        if node_id == self.node and status == "ok":
            log.warning("engine_fault_kill", run=run_id, node=node_id)
            os.kill(os.getpid(), signal.SIGKILL)
