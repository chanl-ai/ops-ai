"""Tool calls through the tool gateway, reads and writes alike: every tool an agent holds is a tools-service
operation (activities/tool_directory.py), and tools-service is where it runs, under the agent service's identity
and the gateway's policy. Nothing runs from the fixture catalogue here.

The gateway checks the approval token against the run's thread and step, so the executor sends both. The thread comes
from `RUN_CONTEXT` when the caller set it (the chat route does), otherwise from the LangGraph config of the node that
is running, which is how graph nodes reach the executor without the kernel's port carrying a thread id. The step is
the call's idempotency key, which a resumed call keeps across processes.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Protocol, cast

import httpx

from ops_agent_kernel.ports import ToolOutcome
from ops_identity import ServiceCallError, ServiceClient

from .shaper import shape_part
from .tool_directory import ToolDirectory, ToolsUnavailable


@dataclass(frozen=True)
class RunContext:
    thread: str | None
    act: str | None = None
    # The lease generation of the run making the call; the gateway refuses a write from a superseded owner (E2b).
    generation: int | None = None
    # Which of a connection's environments the call uses (c-330): live runs and chats production, test runs and test
    # chats test. None says nothing, and the gateway then uses test.
    environment: str | None = None
    # The engine run making the call, whose starter the call acts for (c-558); None outside a run.
    run_id: str | None = None


TEST, PRODUCTION = "test", "production"


def environment_of(mode: str | None) -> str | None:
    """An engine run's mode as the environment its calls use: a test run test, a live one production."""
    return None if mode is None else TEST if mode == "test" else PRODUCTION


RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar("ops_run_context", default=None)


def current_run_context() -> RunContext:
    if (ctx := RUN_CONTEXT.get()) is not None:
        return ctx
    try:
        from langgraph.config import get_config  # noqa: PLC0415 - only graph runs have one

        configurable: dict[str, Any] = get_config().get("configurable") or {}
        return RunContext(
            thread=configurable.get("thread_id"),
            act="graph",
            generation=configurable.get("lease_generation"),
            environment=environment_of(configurable.get("engine_mode")),
            run_id=configurable.get("run_id"),
        )
    except (ImportError, RuntimeError):
        return RunContext(thread=None)


@contextmanager
def acting_as(act: str, environment: str | None = None) -> Generator[None]:
    """Calls made inside name `act` (e.g. `agent:ag_dispute`) as their actor in the gateway's log, on the run's thread
    and lease generation, in `environment` when given, else the run's."""
    base = current_run_context()
    env = environment or base.environment
    token = RUN_CONTEXT.set(replace(base, act=act, environment=env))
    try:
        yield
    finally:
        RUN_CONTEXT.reset(token)


class GatewayRefused(Exception):
    def __init__(self, message: str, reasons: list[str], code: str | None = None) -> None:
        super().__init__(message)
        self.reasons = reasons
        # The gateway's refusal code: needs_review is its check before sending (c-300), which waits for a person.
        self.code = code


EXPIRED = "approval token has expired"
# The gateway refuses a write its check before sending wants a person for with this code (tools-service send_check).
NEEDS_REVIEW_CODE = "needs_review"
NEEDS_REVIEW = "the approval is too old to renew; it needs a fresh review"


class TokenRenewer(Protocol):
    async def renew(self, token: str) -> str | None:
        """A fresh token for the same call and approvers while their recorded approvals stand; None otherwise."""
        ...


class ActingForHeaders(Protocol):
    """Whom a call acts for, as the header tools-service verifies (api/acting_for.py)."""

    async def headers(self, ctx: RunContext, *, tenant_id: str | None, team_id: str | None) -> dict[str, str]: ...


class GatewayClient:
    def __init__(self, tools: ServiceClient) -> None:
        """`tools` calls tools-service as this service, naming the tenant of the run it calls for; tools-service takes
        the caller from the token, never from the body (I13)."""
        self.tools = tools
        # Set by the agents service once it runs: renews an approval token that expired between decision and call.
        self.renewer: TokenRenewer | None = None
        # Set by the agents service once it runs: the token naming whom each call acts for (c-558).
        self.people: ActingForHeaders | None = None

    @property
    def http(self) -> httpx.AsyncClient:
        """The connection to tools-service, for a client with other scopes on it (the mailbox routes)."""
        return self.tools.http

    async def tool_access(self, tool: str) -> str:
        """The tool's access class as tools-service's registry has it; "unknown" when it is not registered."""
        return str((await self.tool_policy(tool))["access"])

    async def tool_policy(self, tool: str) -> dict[str, Any]:
        """The tool's access class and write approval policy (`approval`: approvers, stepUp) as
        tools-service's registry has them; access "unknown" and no policy when it is not registered."""
        try:
            return cast(dict[str, Any], await self.tools.get(f"/v1/tools/{tool}"))
        except ServiceCallError as e:
            if e.status == 404:
                return {"access": "unknown", "approval": None}
            raise

    async def review_decision(self, module_id: str, decision: dict[str, Any]) -> None:
        """Applies a tool module review's decision in tools-service (c-163): publish the reviewed version, or return it
        to draft or withdraw it. Raises on any answer but success, so the request stays marked to apply again."""
        await self.tools.post(f"/v1/tool-modules/{module_id}/review-decisions", decision)

    async def raise_fence(self, thread_id: str, generation: int) -> int:
        """Raises the thread's write fence in tools-service to `generation` (E2c) and returns the fence. Raises
        GatewayRefused when the fence is already higher: this generation is stale too."""
        try:
            data = cast(
                dict[str, Any], await self.tools.post("/v1/fences", {"thread": thread_id, "generation": generation})
            )
        except ServiceCallError as e:
            if e.status == 409:
                raise GatewayRefused(str(e), ["lease superseded"]) from e
            raise
        return int(data["generation"])

    async def evaluate(
        self, expressions: dict[str, str], values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        """A Calculate step's formulas evaluated in tools-service's sandbox (POST /v1/expressions/evaluate): their
        values by name, or None and why a formula failed. Any other refusal or no answer raises."""
        try:
            data = await self.tools.post("/v1/expressions/evaluate", {"expressions": expressions, "values": values})
        except ServiceCallError as e:
            if e.status == 400:
                return None, str(e)
            raise
        return dict(cast(dict[str, Any], data)["out"]), None

    async def abandon(self, key: str, tool: str, thread: str | None) -> dict[str, Any]:
        """The gateway's call under idempotency key `key`, or, when it has none, the key abandoned so that call is
        refused if it arrives later: `{abandoned, call}` (POST /v1/calls/abandon). How a workflow run settles a write
        it lost the answer to."""
        return cast(
            dict[str, Any], await self.tools.post("/v1/calls/abandon", {"key": key, "tool": tool, "thread": thread})
        )

    async def call(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> dict[str, Any]:
        try:
            return await self._call(tool, arguments, key=key, approval_token=approval_token)
        except GatewayRefused as e:
            # A resume retried or recovered after the token's TTL: renew it from the recorded approvals of this exact
            # call and try once more; past the renewal age the reviewers have to decide again.
            if EXPIRED not in e.reasons or approval_token is None or self.renewer is None:
                raise
            renewed = await self.renewer.renew(approval_token)
            if renewed is None:
                raise GatewayRefused(NEEDS_REVIEW, [NEEDS_REVIEW]) from e
            return await self._call(tool, arguments, key=key, approval_token=renewed)

    async def _call(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> dict[str, Any]:
        ctx = current_run_context()
        # The lease generation travels as a header; the gateway fences writes on it (E2b).
        headers = {"X-Lease-Generation": str(ctx.generation)} if ctx.generation is not None else {}
        if self.people is not None:
            headers |= await self.people.headers(ctx, tenant_id=self.tools.tenant(), team_id=self.tools.team())
        body = {
            "tool": tool,
            "input": arguments,
            "key": key,
            "runContext": {
                "thread": ctx.thread,
                "step": key,
                "act": ctx.act,
                **({"environment": ctx.environment} if ctx.environment else {}),
            },
            "approvalToken": approval_token,
        }
        try:
            return cast(dict[str, Any], await self.tools.post("/v1/calls", body, headers=headers))
        except ServiceCallError as e:
            if e.status in (403, 409):
                raise GatewayRefused(str(e), [str(r) for r in (e.details or {}).get("reasons", [])], code=e.code) from e
            raise


def gateway_error(e: ServiceCallError) -> dict[str, Any]:
    """The gateway's error envelope as a tool outcome: code, message, status and details."""
    return {"code": e.code, "message": str(e), "status": e.status, **({"details": e.details} if e.details else {})}


class GatewayToolExecutor:
    def __init__(self, gateway: GatewayClient, directory: ToolDirectory | None = None) -> None:
        """`directory` names each operation's declared result shape (`x-ops-shape`); without it shapes are inferred."""
        self._gateway = gateway
        self._directory = directory

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        # The kernel calls only tools in the turn's grants; the gateway resolves the name in the registry and refuses
        # one it does not hold or that is hidden, unpublished or drifted.
        try:
            data = await self._gateway.call(tool, arguments, key=key, approval_token=approval_token)
        except GatewayRefused as e:
            if e.code == NEEDS_REVIEW_CODE:
                # Check before sending (c-300): the kernel pauses the turn for a person with the reason.
                why = e.reasons[0] if e.reasons else str(e)
                return ToolOutcome(False, f"This needs a person's approval first: {why}", needs_review=why)
            # Back to the model as information, like any tool error; the gateway has logged the refusal.
            return ToolOutcome(False, f"The tool gateway refused this call: {e}.")
        except ServiceCallError as e:
            # 422 invalid input and the like: the gateway's error envelope is the outcome, not an exception that
            # would end a graph run or a turn.
            return ToolOutcome(False, {"error": gateway_error(e)})
        view = data.get("view")
        if data["ok"] and view is None:
            # A shaped result is drawn by the console's widget registry; the chat names it after the call (wp_<id>).
            part = shape_part(data["output"], part_id="", declared=await self._declared(tool))
            view = {"part": part} if part is not None else None
        return ToolOutcome(bool(data["ok"]), data["output"], view)

    async def _declared(self, tool: str) -> str | None:
        if self._directory is None:
            return None
        try:
            ops = await self._directory.operations()
        except ToolsUnavailable:
            return None
        return next((o.output_shape for o in ops if o.name == tool), None)


class GatewayReplySender:
    """send_reply through the gateway; the input it sends is the one the reviewer's token was bound to."""

    def __init__(self, gateway: GatewayClient) -> None:
        self._gateway = gateway

    async def send(self, *, key: str, to: str, subject: str, body: str, approval_token: str | None = None) -> str:
        data = await self._gateway.call(
            "send_reply", {"to": to, "subject": subject, "body": body}, key=key, approval_token=approval_token
        )
        return str(data["output"]["reference"])
