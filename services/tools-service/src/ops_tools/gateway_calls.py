"""The one call path (c-356): every tool call, whichever route took it, is decided and run here. POST /v1/calls and the
MCP adapter build a `CallRequest`, call `GatewayCalls.call` with the verified caller, and map the outcome to their own
wire form, so a call over MCP meets every rule a REST call meets: the registry decides the access class, the schema and
limits hold, check before sending judges a write with no approval, OPA checks the approval token, writes are claimed
once, the per-operation rate is spent, the executor runs on the egress policy, and the call log keeps the row.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, cast

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Principal
from ops_policy import input_hash
from ops_service_kit.ids import new_id, now_iso

from .auth.kinds import TEST
from .executor import Executor, invalid_fields
from .limits import amount_refusal
from .modules.review_events import SYSTEM_TOOLS
from .opa import OpaClient
from .registry import Resolved, ToolRegistry
from .send_check import NEEDS_REVIEW, SendCheck
from .store import CallAbandonedError, CallLog, LeaseSupersededError
from .store.modules import Aggregate
from .store.rate_windows import RateWindows
from .tokens import claims_of
from .tools import ToolCaller

API, MCP = "api", "mcp"


@dataclass(frozen=True)
class CallRequest:
    tool: str
    input: dict[str, Any]
    key: str
    # thread, step, act and environment, as POST /v1/calls' runContext carries them.
    run_context: dict[str, Any] = field(default_factory=dict[str, Any])
    approval_token: str | None = None


@dataclass(frozen=True)
class Allowed:
    call_id: str
    ok: bool
    output: Any
    view: Any = None
    replay_of: str | None = None


@dataclass(frozen=True)
class Refused:
    call_id: str
    status: int
    code: str
    reasons: list[str]
    # What the refusal adds for the caller: the rate limit and its reset, or the fields that failed the schema.
    details: dict[str, Any] = field(default_factory=dict[str, Any])


Outcome = Allowed | Refused


def _token_ref(token: str | None) -> str | None:
    """What the call log keeps of an approval token: a fingerprint that identifies it and cannot be replayed."""
    return "apt:" + hashlib.sha256(token.encode()).hexdigest()[:32] if token else None


def _error_of(outcome: ToolOutcome) -> dict[str, Any] | None:
    """The executor's {code, message} on a failed call, for the call log."""
    output: Any = outcome.output
    if outcome.ok or not isinstance(output, dict):
        return None
    error: Any = cast(dict[str, Any], output).get("error")
    return cast(dict[str, Any], error) if isinstance(error, dict) else None


def system_call(token: str | None, workflow: str) -> bool:
    """Whether a verified approval token was minted for a run of `workflow` while it is a system workflow (c-257)."""
    try:
        claims = claims_of(token) if token else {}
    except (IndexError, ValueError):
        return False
    return claims.get("system") is True and claims.get("workflow") == workflow


def _approvers(token: str | None) -> list[str]:
    try:
        return list(claims_of(token).get("approvers", [])) if token else []
    except (IndexError, ValueError):
        return []


WRITES = {"write"}


def _before_policy(resolved: Resolved | None, args: dict[str, Any]) -> tuple[int, str, str, list[Any]] | None:
    """Registry checks that need no decision from OPA: a hidden operation, an unpublished or drifted module, or input
    that fails the operation's schema, or an amount over its limit, is refused before the policy is asked and before
    anything leaves the gateway."""
    if resolved is None or resolved.operation is None or resolved.module is None:
        return None
    op, module = resolved.operation, resolved.module
    if not op["enabled"]:
        return 403, "operation_hidden", f"{op['name']} is hidden in {module['display_name']}", []
    if module["status"] != "published":
        return 403, "module_not_published", f"{module['display_name']} is not published", []
    if module["drift"]:
        # The server's tools no longer match what was reviewed; nothing runs until the module is reviewed again.
        return 403, "module_drifted", f"{module['display_name']} has drifted from its reviewed tool list", []
    problems = invalid_fields(op["input"], args)
    if problems:
        fields = ", ".join(f"{p['field']} ({p['message']})" for p in problems)
        return 422, "invalid_input", f"input does not match {op['name']}'s schema: {fields}", problems
    # The amount limit holds before the policy and before any request is built (c-028, shared with the test panel).
    if (over := amount_refusal(op, args)) is not None:
        return over.status, over.code, over.message, []
    return None


class GatewayCalls:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        log: CallLog,
        opa: OpaClient,
        executor: Executor,
        counters: RateWindows,
        send_check: SendCheck | None,
        all_writes_wait: Callable[[str, str | None], Awaitable[bool]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry
        self.log = log
        self.opa = opa
        self.executor = executor
        self.counters = counters
        self.send_check = send_check
        self.all_writes_wait = all_writes_wait
        self.clock = clock

    async def call(
        self,
        caller: Principal,
        req: CallRequest,
        *,
        generation: int | None = None,
        channel: str = API,
        client_name: str | None = None,
        sees: Callable[[Aggregate], bool] | None = None,
    ) -> Outcome:
        """One call for `caller`, the verified principal of whichever route took it. `generation` is a run's lease
        generation (writes are fenced on it); `channel` and `client_name` say where the call came from, for the log.
        `sees` is the caller's team's view of the modules: an operation of a module outside it is refused."""
        call_id = new_id("gwc")
        started = time.monotonic()

        def elapsed() -> int:
            return round((time.monotonic() - started) * 1000)

        resolved = await self.registry.resolve(req.tool, tenant_id=caller.tenant_id)
        access = resolved.access if resolved else "unknown"
        digest = input_hash(req.input)
        ctx = req.run_context
        row: dict[str, Any] = {
            "id": call_id,
            "tenant_id": caller.tenant_id,
            "tool": req.tool,
            "access": access,
            "input_hash": digest,
            "idempotency_key": req.key,
            "thread_id": ctx.get("thread"),
            "step": ctx.get("step"),
            "sub": caller.sub,
            "act": ctx.get("act"),
            "approvers": _approvers(req.approval_token),
            "created_at": now_iso(),
            "module_id": resolved.module["id"] if resolved and resolved.module else None,
            "approval_token_id": _token_ref(req.approval_token),
            "environment": ctx.get("environment") or TEST,
            "connection_id": resolved.module.get("connection_id") if resolved and resolved.module else None,
            "channel": channel,
            "client_name": client_name,
        }

        async def over_rate() -> Refused | None:
            """Spends one of the operation's calls this minute; past the limit the call is refused and logged. Only a
            call that passed every other check and is about to run spends one (c-028)."""
            if resolved is None or resolved.operation is None:
                return None
            op = resolved.operation
            limit = int(op["rate_limit_per_min"])
            spent = await self.counters.spend(caller.tenant_id, op["name"], limit)
            if spent.allowed:
                return None
            reason = f"rate limit of {limit} calls a minute reached for {op['name']}"
            row.update(decision="deny", reasons=[reason])
            error = {"code": "RATE_LIMITED", "message": reason}
            if access in WRITES:
                await self.log.refuse_claimed(call_id, reasons=[reason], error=error, latency_ms=elapsed())
            else:
                await self.log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return Refused(call_id, 429, "RATE_LIMITED", [reason], {"limit": limit, "resetAt": spent.reset_at})

        if sees is not None and resolved is not None and resolved.module is not None and not sees(resolved.module):
            reason = f"{req.tool} belongs to a module outside this team"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row, outcome="refused", latency_ms=elapsed(), error={"code": "team_forbidden", "message": reason}
            )
            return Refused(call_id, 403, "team_forbidden", [reason])
        early = _before_policy(resolved, req.input)
        if early is not None:
            status, code, reason, problems = early
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row, outcome="refused", latency_ms=elapsed(), error={"code": code, "message": reason}
            )
            return Refused(call_id, status, code, [reason], {"invalid": problems} if problems else {})
        policy = await self.registry.policy_for(req.tool, caller.tenant_id) if resolved else None
        # From the registry and the team's policy, never the caller: whether this write needs an approval token. A
        # write declared to run at once (open_case) still waits while the team has every write wait.
        approval_required = access not in WRITES or (
            # Over MCP every write waits for a person, whatever the operation declares (owner, c-354 Q4).
            channel == MCP
            or await self.registry.requires_approval(req.tool, caller.tenant_id)
            or await self.all_writes_wait(caller.tenant_id, caller.team_id)
        )
        if access in WRITES and req.approval_token is None and self.send_check is not None:
            # Check before sending (c-300): a write the team's sending policy forbids, or one the check could not
            # judge, waits for a person; a write that carries an approval was decided by one and is not judged again.
            why = await self.send_check.needs_person(caller.tenant_id, caller.team_id, req.tool, req.input, digest)
            if why is not None:
                row.update(decision="deny", reasons=[why])
                await self.log.record(
                    **row, outcome="refused", latency_ms=elapsed(), error={"code": NEEDS_REVIEW, "message": why}
                )
                return Refused(call_id, 409, NEEDS_REVIEW, [why])
        decision = await self.opa.decide(
            {
                "tool": req.tool,
                "access": access,
                "approval_required": approval_required,
                # From the registry, never the caller: how many distinct people the token must name.
                "approvers_required": policy["approvers"] if policy else None,
                "input_hash": digest,
                "run_context": {**ctx, "sub": caller.sub},
                "token": req.approval_token,
                "now_ns": int(self.clock() * 1_000_000_000),
                # Set from the route that took the call, never by the caller: the registered rule reads it.
                "channel": channel,
            }
        )
        row.update(decision="allow" if decision.allow else "deny", reasons=decision.reasons)
        if not decision.allow:
            error = {"code": "gateway_refused", "message": "; ".join(decision.reasons)}
            await self.log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return Refused(call_id, 403, "gateway_refused", decision.reasons)
        if req.tool in SYSTEM_TOOLS and not system_call(req.approval_token, SYSTEM_TOOLS[req.tool]):
            # The token is verified by now; it must have been minted for the one system workflow this tool serves.
            reason = f"{req.tool} is applied only by the {SYSTEM_TOOLS[req.tool]} system workflow"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(
                **row,
                outcome="refused",
                latency_ms=elapsed(),
                error={"code": "system_workflow_only", "message": reason},
            )
            return Refused(call_id, 403, "system_workflow_only", [reason])
        if access not in WRITES:
            if (limited := await over_rate()) is not None:
                return limited
            outcome = await self.executor.run(
                resolved or Resolved(access, "local"),
                req.tool,
                req.input,
                key=req.key,
                caller=ToolCaller.of(caller),
                environment=ctx.get("environment"),
            )
            failed = _error_of(outcome)
            await self.log.record(**row, outcome="ok" if outcome.ok else "error", latency_ms=elapsed(), error=failed)
            return Allowed(call_id, outcome.ok, outcome.output, outcome.view)
        try:
            # The caller's lease generation arrives as the X-Lease-Generation header; the fence is checked in the
            # claim's own transaction, before the dedup lookup (ADR-0016).
            first = await self.log.claim(generation=generation, **row)
        except LeaseSupersededError:
            row.update(decision="deny", reasons=["lease superseded"])
            await self.log.record(**row, outcome="refused")
            return Refused(call_id, 409, "lease_superseded", ["lease superseded"])
        except CallAbandonedError:
            # Its caller found no record of it and moved on (a workflow's error port); running it now would act twice.
            reason = "this write's caller abandoned its key after losing the answer; it does not run"
            row.update(decision="deny", reasons=[reason])
            await self.log.record(**row, outcome="refused", error={"code": "CALL_ABANDONED", "message": reason})
            return Refused(call_id, 409, "call_abandoned", [reason])
        if first is not None:
            if first["outcome"] == "running":
                reason = "the same write is already running; retry after it finishes"
                # A refusal like any other, so the log, the module's Denied count and the response agree.
                row.update(decision="deny", reasons=[reason])
                error = {"code": "WRITE_IN_PROGRESS", "message": reason}
                await self.log.record(**row, outcome="in_progress", latency_ms=elapsed(), error=error)
                return Refused(call_id, 409, "write_in_progress", [reason])
            # The same approved write again: answer with the first result, run nothing.
            await self.log.record(
                **row, outcome="replayed", output=first["output"], view=first["view"], replay_of=first["id"]
            )
            return Allowed(call_id, first["outcome"] == "ok", first["output"], first["view"], replay_of=first["id"])
        if (limited := await over_rate()) is not None:
            return limited
        approvers = tuple(_approvers(req.approval_token))
        outcome = await self.executor.run(
            resolved or Resolved(access, "local"),
            req.tool,
            req.input,
            key=req.key,
            caller=ToolCaller.of(caller, approvers=approvers),
            environment=ctx.get("environment"),
        )
        failed = _error_of(outcome)
        await self.log.finish(
            call_id,
            outcome="ok" if outcome.ok else "error",
            output=outcome.output,
            view=outcome.view,
            latency_ms=elapsed(),
            error=failed,
        )
        return Allowed(call_id, outcome.ok, outcome.output, outcome.view)
