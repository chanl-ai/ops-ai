"""POST /v1/calls: hash the input, ask OPA, log the decision, and run the tool only when OPA allows it."""

from __future__ import annotations

import hashlib
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast

import httpx
from fastapi import APIRouter, FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import Auth, CurrentService, install_auth
from ops_policy import input_hash
from ops_service_kit.http import Envelope, Out, error_body, error_responses, install_error_handlers
from ops_service_kit.ids import new_id, now_iso
from ops_service_kit.settings import Settings

from .egress import EgressPolicy, egress_client
from .executor import Executor, HttpExecutor, invalid_fields
from .limits import amount_refusal
from .opa import POLICY_FILE, OpaClient, PolicyMismatchError, policy_hash
from .registry import Resolved, ToolRegistry
from .secrets import SecretResolver
from .store import CallLog, LeaseSupersededError
from .store.rate_windows import RateWindows
from .tokens import claims_of
from .tools import ToolRunner


class _Wire(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RunContext(_Wire):
    """Where the call comes from. Who calls is not here: it is the verified service token's subject (I13)."""

    thread: str | None = None
    step: str | None = None
    act: str | None = None


class FenceIn(_Wire):
    thread: str
    generation: int = Field(ge=1)


class CallIn(_Wire):
    tool: str
    input: dict[str, Any]
    key: str
    run_context: RunContext = Field(alias="runContext")
    approval_token: str | None = Field(default=None, alias="approvalToken")


class CallResult(Out):
    call_id: str
    decision: str
    ok: bool
    output: Any
    view: Any = None
    replay_of: str | None = None


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


def _approvers(token: str | None) -> list[str]:
    try:
        return list(claims_of(token).get("approvers", [])) if token else []
    except (IndexError, ValueError):
        return []


WRITES = {"write", "money_movement"}


def _allowed(call_id: str, ok: bool, output: Any, view: Any, *, replay_of: str | None = None) -> JSONResponse:
    data: dict[str, Any] = {"callId": call_id, "decision": "allow", "ok": ok, "output": output, "view": view}
    if replay_of:
        data["replayOf"] = replay_of
    return JSONResponse({"success": True, "data": data})


def _refused(call_id: str, status: int, code: str, reasons: list[str], **details: Any) -> JSONResponse:
    body = error_body(status, code, "; ".join(reasons))
    body["error"]["details"] = {"callId": call_id, "reasons": reasons, **details}
    return JSONResponse(body, status_code=status)


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


def create_gateway_app(
    *,
    opa: OpaClient,
    registry: ToolRegistry,
    log: CallLog,
    runner: ToolRunner,
    review_key: str,
    auth: Auth | None = None,
    rates: RateWindows | None = None,
    clock: Callable[[], float] = time.time,
    policy: str | None = None,
    routers: tuple[APIRouter, ...] = (),
    http_client: httpx.AsyncClient | None = None,
    egress: EgressPolicy | None = None,
    secret_resolver: SecretResolver | None = None,
    cors_origins: tuple[str, ...] = (),
) -> FastAPI:
    """`clock` is the time a token's expiry is judged by, sent to OPA with each call; tests pass a fixed one.
    `policy` is the Rego the gateway decides by, `policy/gateway.rego` unless given; it is written into OPA at start
    and checked there on every health probe. `routers` mounts the registry's routes (`ops_tools.modules`).
    `egress` is the policy every outbound request follows; without it no http operation runs. `http_client` is what
    those requests go through: by default the policy's own client, in tests one bound to a fake API.
    `secret_resolver` resolves `{{NAME}}` header references at call time; without it an operation needing a secret
    is refused. `cors_origins` are the browser origins (the console) allowed to call these routes. `auth` resolves
    callers (ops_identity's shared dependency); by default it is built from Settings for audience "tools"."""
    rules = policy if policy is not None else POLICY_FILE.read_text()
    client = http_client or (egress_client(egress) if egress else httpx.AsyncClient())
    executor = Executor(runner, HttpExecutor(client, egress, secret_resolver))
    expected = policy_hash(rules)
    counters = rates or RateWindows(log.engine)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        await opa.load_review_key(review_key)
        await opa.load_policy(rules)
        if await opa.loaded_policy_hash() != expected:
            raise PolicyMismatchError("OPA does not hold this gateway's policy after loading it; refusing to start.")
        yield

    app = FastAPI(title="Ops AI tool gateway", lifespan=lifespan)
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(Settings(), audience="tools"))
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id"],
            max_age=600,
        )
    for router in routers:
        app.include_router(router)

    @app.get("/health", response_model=None, tags=["gateway"])
    async def health() -> dict[str, str] | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Another process writing a different policy into a shared OPA would change every decision; say so.
        if await opa.loaded_policy_hash() != expected:
            return JSONResponse({"status": "policy_drift"}, status_code=503)
        return {"status": "ok"}

    @app.get("/v1/tools/{name}", tags=["gateway"])
    async def tool_access(name: str, _: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token): a tool's access class from the gateway's registry, the one the policy decides
        on. The review service asks here how many approvers a call needs instead of reading the registry itself."""
        access = registry.access(name)
        if access == "unknown":
            return _refused("", 404, "not_found", [f"tool {name} is not registered with the gateway"])
        return JSONResponse({"success": True, "data": {"name": name, "access": access}})

    @app.post("/v1/fences", tags=["gateway"])
    async def raise_fence(body: FenceIn, _: CurrentService) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Internal (service token): agents-service calls it when it takes a thread over, so the new generation is
        the fence before any write of the new owner, and a stalled old owner cannot write in between. Idempotent;
        a lower generation than the fence is refused."""
        current = await log.raise_fence(body.thread, body.generation)
        if current > body.generation:
            return _refused("", 409, "lease_superseded", [f"fence is at generation {current}"])
        return JSONResponse({"success": True, "data": {"thread": body.thread, "generation": current}})

    @app.post("/v1/calls", tags=["gateway"], response_model=Envelope[CallResult], responses=error_responses())
    async def call(  # pyright: ignore[reportUnusedFunction]
        body: CallIn, caller: CurrentService, x_lease_generation: Annotated[int | None, Header()] = None
    ) -> JSONResponse:
        call_id = new_id("gwc")
        started = time.monotonic()

        def elapsed() -> int:
            return round((time.monotonic() - started) * 1000)

        resolved = await registry.resolve(body.tool, tenant_id=caller.tenant_id)
        access = resolved.access if resolved else "unknown"
        digest = input_hash(body.input)
        ctx = body.run_context
        row: dict[str, Any] = {
            "id": call_id,
            "tool": body.tool,
            "access": access,
            "input_hash": digest,
            "idempotency_key": body.key,
            "thread_id": ctx.thread,
            "step": ctx.step,
            "sub": caller.sub,
            "act": ctx.act,
            "approvers": _approvers(body.approval_token),
            "created_at": now_iso(),
            "module_id": resolved.module["id"] if resolved and resolved.module else None,
            "approval_token_id": _token_ref(body.approval_token),
        }

        async def over_rate() -> JSONResponse | None:
            """Spends one of the operation's calls this minute; past the limit the call is refused and logged. Only a
            call that passed every other check and is about to run spends one (c-028)."""
            if resolved is None or resolved.operation is None:
                return None
            op = resolved.operation
            limit = int(op["rate_limit_per_min"])
            spent = await counters.spend(caller.tenant_id, op["name"], limit)
            if spent.allowed:
                return None
            reason = f"rate limit of {limit} calls a minute reached for {op['name']}"
            row.update(decision="deny", reasons=[reason])
            error = {"code": "RATE_LIMITED", "message": reason}
            if access in WRITES:
                await log.refuse_claimed(call_id, reasons=[reason], error=error, latency_ms=elapsed())
            else:
                await log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return _refused(call_id, 429, "RATE_LIMITED", [reason], limit=limit, resetAt=spent.reset_at)

        early = _before_policy(resolved, body.input)
        if early is not None:
            status, code, reason, problems = early
            row.update(decision="deny", reasons=[reason])
            await log.record(**row, outcome="refused", latency_ms=elapsed(), error={"code": code, "message": reason})
            return _refused(call_id, status, code, [reason], **({"invalid": problems} if problems else {}))
        decision = await opa.decide(
            {
                "tool": body.tool,
                "access": access,
                "input_hash": digest,
                "run_context": {**ctx.model_dump(), "sub": caller.sub},
                "token": body.approval_token,
                "now_ns": int(clock() * 1_000_000_000),
            }
        )
        row.update(decision="allow" if decision.allow else "deny", reasons=decision.reasons)
        if not decision.allow:
            error = {"code": "gateway_refused", "message": "; ".join(decision.reasons)}
            await log.record(**row, outcome="refused", latency_ms=elapsed(), error=error)
            return _refused(call_id, 403, "gateway_refused", decision.reasons)
        if access not in WRITES:
            if (limited := await over_rate()) is not None:
                return limited
            outcome = await executor.run(
                resolved or Resolved(access, "local"), body.tool, body.input, key=body.key, actor=caller.sub
            )
            failed = _error_of(outcome)
            await log.record(**row, outcome="ok" if outcome.ok else "error", latency_ms=elapsed(), error=failed)
            return _allowed(call_id, outcome.ok, outcome.output, outcome.view)
        try:
            # The caller's lease generation arrives as the X-Lease-Generation header; the fence is checked in the
            # claim's own transaction, before the dedup lookup (ADR-0016).
            first = await log.claim(generation=x_lease_generation, **row)
        except LeaseSupersededError:
            row.update(decision="deny", reasons=["lease superseded"])
            await log.record(**row, outcome="refused")
            return _refused(call_id, 409, "lease_superseded", ["lease superseded"])
        if first is not None:
            if first["outcome"] == "running":
                await log.record(**row, outcome="in_progress")
                return _refused(
                    call_id, 409, "write_in_progress", ["the same write is already running; retry after it finishes"]
                )
            # The same approved write again: answer with the first result, run nothing.
            await log.record(**row, outcome="replayed", output=first["output"], view=first["view"])
            return _allowed(call_id, first["outcome"] == "ok", first["output"], first["view"], replay_of=first["id"])
        if (limited := await over_rate()) is not None:
            return limited
        outcome = await executor.run(
            resolved or Resolved(access, "local"), body.tool, body.input, key=body.key, actor=caller.sub
        )
        failed = _error_of(outcome)
        await log.finish(
            call_id,
            outcome="ok" if outcome.ok else "error",
            output=outcome.output,
            view=outcome.view,
            latency_ms=elapsed(),
            error=failed,
        )
        return _allowed(call_id, outcome.ok, outcome.output, outcome.view)

    return app
