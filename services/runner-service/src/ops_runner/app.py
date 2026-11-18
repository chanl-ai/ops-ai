"""runner-service routes: `POST /v1/runs` runs one function, and `/health`.

Only tools-service calls it, with a service token naming the tenant and team the call is for. Each `ops.call` from the
function goes back to tools-service at `POST /v1/code-runs/calls` with the runner's own service token and the run's
call token from tools-service; tools-service decides the call as the original caller, so the runner holds no grant of
its own. A run holds a worker thread for its length; `runner_concurrency` bounds how many run at once."""

from __future__ import annotations

import asyncio
import time
from typing import Annotated, Any

import anyio
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_identity import (
    Auth,
    Principal,
    ServiceCallError,
    ServiceClient,
    ServiceUnreachable,
    current_service,
    install_auth,
)
from ops_service_kit.http import (
    Envelope,
    In,
    JsonValue,
    Out,
    error_responses,
    install_error_handlers,
    ok,
    operation_id,
)
from ops_service_kit.settings import Settings

from .domain import (
    DEFAULT_CALLS,
    DEFAULT_MEMORY_MB,
    DEFAULT_TIME_S,
    CallAnswer,
    CallReply,
    Limits,
    RunResult,
    failure,
)
from .wasm import WasmPython

SOURCE_CAP = 100_000


class LimitsIn(In):
    memory_mb: int = Field(default=DEFAULT_MEMORY_MB, ge=32)
    time_s: float = Field(default=DEFAULT_TIME_S, gt=0)
    calls: int = Field(default=DEFAULT_CALLS, ge=0)


class RunIn(In):
    source: str = Field(min_length=1, max_length=SOURCE_CAP)
    entry: str = Field(default="main", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    input: Any = None
    limits: LimitsIn = Field(default_factory=LimitsIn)
    # tools-service's token for this run's calls back to it; without one every `ops.call` is refused.
    call_token: str | None = None


class TraceOut(Out):
    tool: str
    ok: bool
    code: str | None = None


class ErrorOut(Out):
    code: str
    message: str


class RunOut(Out):
    ok: bool
    output: JsonValue = None
    error: ErrorOut | None = None
    log: str
    calls: int
    create_ms: int
    execute_ms: int
    trace: list[TraceOut]


class Health(Out):
    status: str
    running: int
    capacity: int


def capped(asked: LimitsIn, settings: Settings) -> Limits:
    """The run's limits, each held to the deployment's cap whatever the caller asked for."""
    return Limits(
        memory_mb=min(asked.memory_mb, settings.runner_max_memory_mb),
        time_s=min(asked.time_s, settings.runner_max_time_s),
        calls=min(asked.calls, settings.runner_max_calls),
    )


def calls_to_tools(tools: ServiceClient | None, caller: Principal, token: str | None, deadline: float) -> CallAnswer:
    """The answer to each `ops.call`: a call to tools-service for the run's tenant and team. It runs on the guest's
    worker thread and hands the request to the event loop, which owns the client. A call waits only for the time left
    before the run's deadline (`time.monotonic()`), so calls together never hold a run past its limit; one that
    answers later fails `call_failed`."""

    async def call(client: ServiceClient, call_token: str, tool: str, args: dict[str, JsonValue]) -> CallReply:
        late: CallReply = {
            "ok": False,
            "error": failure("call_failed", "The tool did not answer within the run's time limit."),
        }
        if (left := deadline - time.monotonic()) <= 0:
            return late
        try:
            async with asyncio.timeout(left):
                data = await client.post(
                    "/v1/code-runs/calls",
                    json={"tool": tool, "input": args},
                    headers={"X-Code-Run": call_token},
                    tenant=caller.tenant_id,
                    team=caller.team_id,
                    timeout=left,
                )
        except TimeoutError:
            return late
        except ServiceCallError as e:
            return {"ok": False, "error": failure(e.code, e.message)}
        except ServiceUnreachable:
            return {"ok": False, "error": failure("call_failed", "The gateway did not answer.")}
        return replied(data)

    def answer(tool: str, args: dict[str, JsonValue]) -> CallReply:
        if tools is None or not token:
            return {"ok": False, "error": failure("calls_unavailable", "This run cannot call tools.")}
        return anyio.from_thread.run(call, tools, token, tool, args)

    return answer


def replied(data: JsonValue) -> CallReply:
    """tools-service's answer to a call, as the guest reads it: an answer with no `ok` is a failed call, and an error
    keeps only its code and message."""
    out: dict[str, JsonValue] = data if isinstance(data, dict) else {}
    error = out.get("error")
    if not isinstance(error, dict):
        return {"ok": bool(out.get("ok")), "output": out.get("output"), "error": None}
    code, message = error.get("code", "call_failed"), error.get("message", "")
    return {"ok": bool(out.get("ok")), "output": out.get("output"), "error": failure(str(code), str(message))}


def reply(result: RunResult) -> RunOut:
    error = result.error
    return RunOut(
        ok=result.ok,
        output=result.output,
        error=ErrorOut(code=error["code"], message=error["message"]) if error else None,
        log=result.log,
        calls=result.calls,
        create_ms=result.create_ms,
        execute_ms=result.execute_ms,
        trace=[TraceOut(tool=t["tool"], ok=t["ok"], code=t["code"]) for t in result.trace],
    )


def create_runner_app(
    runtime: WasmPython,
    *,
    settings: Settings,
    tools: ServiceClient | None,
    auth: Auth | None = None,
) -> FastAPI:
    app = FastAPI(title="Ops AI runner service", version="0.1.0", generate_unique_id_function=operation_id)
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(settings, audience="runner"))
    slots = asyncio.Semaphore(settings.runner_concurrency)
    running = 0

    @app.get("/health", tags=["health"], response_model=Health)
    async def health() -> Health:  # pyright: ignore[reportUnusedFunction]
        return Health(status="ok", running=running, capacity=settings.runner_concurrency)

    @app.post("/v1/runs", tags=["runs"], response_model=Envelope[RunOut], responses=error_responses())
    async def run(  # pyright: ignore[reportUnusedFunction]
        body: RunIn, caller: Annotated[Principal, Depends(current_service)]
    ) -> JSONResponse:
        """Runs `entry(input)` from `source` in a fresh sandbox and answers when it ends: its output or the error that
        stopped it (`time_limit`, `memory_limit`, `function_error`, or a refused call's code), its log and timings."""
        nonlocal running
        limits = capped(body.limits, settings)
        async with slots:
            running += 1
            try:
                # The deadline is read on the worker thread as the run starts, not before its wait for a slot.
                result: RunResult = await anyio.to_thread.run_sync(
                    lambda: runtime.run(
                        body.source,
                        body.entry,
                        body.input,
                        limits,
                        calls_to_tools(tools, caller, body.call_token, time.monotonic() + limits.time_s),
                    )
                )
            finally:
                running -= 1
        return ok(reply(result).model_dump(mode="json", by_alias=True))

    return app
