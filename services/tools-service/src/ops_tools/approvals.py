"""Approval tokens are minted here and nowhere else (docs/design/agents-v2/tool-gateway.md, "Interfaces").

`POST /v1/calls/decide` answers what `POST /v1/calls` would do with a call, from the same function (`GatewayCalls.call`
with `decide_only`), and sends nothing. `POST /v1/approvals` mints the token for one call once its approvers are
recorded: the call is decided again, the person it acts for may approve it only as the tenant's approval policy lets
an asker decide, and a step whose write already ran under another input is closed. The signing key is the gateway's
alone; OPA verifies with the same key at the call.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from pydantic import Field, model_validator

from ops_identity import ActingForPerson, Principal
from ops_policy import input_hash
from ops_policy.approval import Binding, mint_approval
from ops_service_kit.errors import Conflict, Forbidden, Unprocessable
from ops_service_kit.http import In, Json, Out

from .gateway_calls import ACCESS, Allowed, CallRequest, Decided, GatewayCalls, Outcome, Refused
from .modules.policy import asker_refusal
from .store import CallLog


class DecideResult(Out):
    """`POST /v1/calls/decide`: whether the call would run, wait for a person, or be refused, and what an approval of
    it would be bound to. `code` is the refusal's code, as `POST /v1/calls` would answer it."""

    verdict: Literal["allow", "needs_review", "refuse"]
    reason: str
    input_hash: str
    approvers_needed: int
    editable: bool
    code: str | None = None


def decide_result(outcome: Outcome, digest: str) -> DecideResult:
    if isinstance(outcome, Refused):
        reason = "; ".join(outcome.reasons)
        return DecideResult(
            verdict="refuse", reason=reason, input_hash=digest, approvers_needed=0, editable=False, code=outcome.code
        )
    found = outcome.decided or Decided(digest, 0)
    return DecideResult(
        verdict="needs_review" if found.needs_review else "allow",
        reason=found.reason,
        input_hash=found.input_hash,
        approvers_needed=found.approvers_needed,
        # A person reviewing a held write may change its input before approving; the approval binds what they send.
        editable=found.needs_review,
    )


class ApprovalBindingIn(In):
    thread_id: str | None = Field(default=None, alias="threadId", min_length=1)
    run_id: str | None = Field(default=None, alias="runId", min_length=1)
    step: str = Field(min_length=1, max_length=200)
    tool: str = Field(min_length=1, max_length=64)
    input_hash: str = Field(alias="inputHash", min_length=1)
    # The workflow whose run the write is in, and whether the platform owns it (the token's `system` claim).
    workflow: str = ""
    system: bool = False

    @model_validator(mode="after")
    def _one_owner(self) -> ApprovalBindingIn:
        if (self.thread_id is None) == (self.run_id is None):
            raise ValueError("name exactly one of threadId and runId")
        return self


class ApprovalIn(In):
    binding: ApprovalBindingIn
    # The call's input, decided again here; its hash must be the binding's.
    input: dict[str, Any]
    # The run the call is made in, as POST /v1/calls' runContext carries it: it picks the account, and so the answer.
    environment: str | None = None
    accounts: dict[str, str] | None = Field(default=None, max_length=50)
    approvers: list[str] = Field(min_length=1, max_length=20)


class ApprovalToken(Out):
    token: str
    expires_at: str


class ApprovalMint:
    def __init__(
        self,
        calls: GatewayCalls,
        log: CallLog,
        key: str,
        ttl_s: int,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.calls = calls
        self.log = log
        self.key = key
        self.ttl_s = ttl_s
        self.clock = clock

    async def mint(self, caller: Principal, body: ApprovalIn, acting: ActingForPerson | None) -> ApprovalToken:
        b = body.binding
        thread = b.thread_id or b.run_id or ""
        if input_hash(body.input) != b.input_hash:
            raise Unprocessable("The input sent is not the input this approval names.", code="input_hash_mismatch")
        ran = [
            c
            for c in await self.log.for_thread(thread, tenant_id=caller.tenant_id)
            if c.step == b.step and c.effect and c.input_hash != b.input_hash
        ]
        if ran:
            # The step sent its write already, with another input: nothing this approval names can run any more.
            raise Conflict(
                "This step already sent its write, so the approval is closed. Ask for a new review of the new call.",
                code="interrupt_closed",
            )
        run_context: Json = {"thread": thread, "step": b.step}
        if body.environment:
            run_context["environment"] = body.environment
        if body.accounts:
            run_context["accounts"] = dict(body.accounts)
        req = CallRequest(tool=b.tool, input=body.input, key=b.step, run_context=run_context, acting_for=acting)
        decided = await self.calls.call(caller, req, decide_only=True)
        if isinstance(decided, Refused):
            raise Forbidden(
                f"This call is refused, so no approval is given: {'; '.join(decided.reasons)}", code=decided.code
            )
        assert isinstance(decided, Allowed)
        confirms = decided.decided is not None and decided.decided.asker_confirms
        if acting is not None and not confirms:
            may_decide = await self.calls.asker_may_decide(caller.tenant_id, acting)
            if asker_refusal(ACCESS, acting, caller.tenant_id, body.approvers, may_decide=may_decide) is not None:
                raise Forbidden(
                    "The person who asked for this cannot approve it: the team's approval policy needs someone else.",
                    code="requester_cannot_approve",
                )
        now = self.clock()
        binding = Binding(
            thread, b.step, b.tool, b.input_hash, list(body.approvers), workflow=b.workflow, system=b.system
        )
        token = mint_approval(binding, self.key, ttl_s=self.ttl_s, now=now)
        expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now + self.ttl_s))
        return ApprovalToken(token=token, expires_at=expires)
