"""Tool calls through the tool gateway, reads and writes alike: every tool an agent holds is a tools-service
operation (activities/tool_directory.py), and tools-service is where it runs, under the agent service's identity
and the gateway's policy. Nothing runs from the fixture catalogue here.

The gateway checks the approval token against the run's thread and step, so the executor sends both. The thread comes
from `RUN_CONTEXT` when the caller set it (the chat route does), otherwise from the LangGraph config of the node that
is running, which is how graph nodes reach the executor without the kernel's port carrying a thread id. The step is
the call's idempotency key, which a resumed call keeps across processes.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ops_agent_kernel.ports import ToolOutcome


@dataclass(frozen=True)
class RunContext:
    thread: str | None
    act: str | None = None
    # The lease generation of the run making the call; the gateway refuses a write from a superseded owner (E2b).
    generation: int | None = None


RUN_CONTEXT: ContextVar[RunContext | None] = ContextVar("ops_run_context", default=None)


def current_run_context() -> RunContext:
    if (ctx := RUN_CONTEXT.get()) is not None:
        return ctx
    try:
        from langgraph.config import get_config  # noqa: PLC0415 - only graph runs have one

        configurable: dict[str, Any] = get_config().get("configurable") or {}
        return RunContext(
            thread=configurable.get("thread_id"), act="graph", generation=configurable.get("lease_generation")
        )
    except (ImportError, RuntimeError):
        return RunContext(thread=None)


@contextmanager
def acting_as(act: str) -> Generator[None]:
    """Calls made inside name `act` (e.g. `agent:ag_dispute`) as their actor in the gateway's log, on the run's thread
    and lease generation."""
    base = current_run_context()
    token = RUN_CONTEXT.set(RunContext(thread=base.thread, act=act, generation=base.generation))
    try:
        yield
    finally:
        RUN_CONTEXT.reset(token)


class GatewayRefused(Exception):
    def __init__(self, message: str, reasons: list[str]) -> None:
        super().__init__(message)
        self.reasons = reasons


EXPIRED = "approval token has expired"
NEEDS_REVIEW = "the approval is too old to renew; it needs a fresh review"


class TokenRenewer(Protocol):
    async def renew(self, token: str) -> str | None:
        """A fresh token for the same call and approvers while their recorded approvals stand; None otherwise."""
        ...


class GatewayClient:
    def __init__(self, client: httpx.AsyncClient, *, token: Callable[[], str]) -> None:
        """`token` mints this service's Ed25519 service token for audience "tools", naming the tenant of the run it
        calls for; tools-service takes the caller from it, never from the body (I13)."""
        self.client = client
        self.token = token
        # Set by the agents service once it runs: renews an approval token that expired between decision and call.
        self.renewer: TokenRenewer | None = None

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    async def tool_access(self, tool: str) -> str:
        """The tool's access class as tools-service's registry has it; "unknown" when it is not registered."""
        return str((await self.tool_policy(tool))["access"])

    async def tool_policy(self, tool: str) -> dict[str, Any]:
        """The tool's access class and write approval policy (`approval`: approvers, approverTeam, selfApproval) as
        tools-service's registry has them; access "unknown" and no policy when it is not registered."""
        r = await self.client.get(f"/v1/tools/{tool}", headers=self._auth())
        if r.status_code == 404:
            return {"access": "unknown", "approval": None}
        r.raise_for_status()
        data: dict[str, Any] = r.json()["data"]
        return data

    async def raise_fence(self, thread_id: str, generation: int) -> int:
        """Raises the thread's write fence in tools-service to `generation` (E2c) and returns the fence. Raises
        GatewayRefused when the fence is already higher: this generation is stale too."""
        r = await self.client.post(
            "/v1/fences",
            headers=self._auth(),
            json={"thread": thread_id, "generation": generation},
        )
        if r.status_code == 409:
            raise GatewayRefused(r.json()["error"]["message"], ["lease superseded"])
        r.raise_for_status()
        return int(r.json()["data"]["generation"])

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
        headers = self._auth() | ({"X-Lease-Generation": str(ctx.generation)} if ctx.generation is not None else {})
        r = await self.client.post(
            "/v1/calls",
            headers=headers,
            json={
                "tool": tool,
                "input": arguments,
                "key": key,
                "runContext": {
                    "thread": ctx.thread,
                    "step": key,
                    "act": ctx.act,
                },
                "approvalToken": approval_token,
            },
        )
        body: dict[str, Any] = r.json()
        if r.status_code in (403, 409):
            err: dict[str, Any] = body["error"]
            raise GatewayRefused(err["message"], list(err.get("details", {}).get("reasons", [])))
        r.raise_for_status()
        return body["data"]


class GatewayToolExecutor:
    def __init__(self, gateway: GatewayClient) -> None:
        self._gateway = gateway

    async def execute(
        self, tool: str, arguments: dict[str, Any], *, key: str, approval_token: str | None
    ) -> ToolOutcome:
        # The kernel calls only tools in the turn's grants; the gateway resolves the name in the registry and refuses
        # one it does not hold or that is hidden, unpublished or drifted.
        try:
            data = await self._gateway.call(tool, arguments, key=key, approval_token=approval_token)
        except GatewayRefused as e:
            # Back to the model as information, like any tool error; the gateway has logged the refusal.
            return ToolOutcome(False, f"The tool gateway refused this call: {e}.")
        return ToolOutcome(bool(data["ok"]), data["output"], data.get("view"))


class GatewayReplySender:
    """send_reply through the gateway; the input it sends is the one the reviewer's token was bound to."""

    def __init__(self, gateway: GatewayClient) -> None:
        self._gateway = gateway

    async def send(self, *, key: str, to: str, subject: str, body: str, approval_token: str | None = None) -> str:
        data = await self._gateway.call(
            "send_reply", {"to": to, "subject": subject, "body": body}, key=key, approval_token=approval_token
        )
        return str(data["output"]["reference"])
