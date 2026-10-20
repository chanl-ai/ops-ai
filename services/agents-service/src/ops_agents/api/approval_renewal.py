"""Renewing an approval token that expired between the decision and the call (durability-failure-and-audit.md).

A decision is resumed at once, but a resume retried after its lease was busy, or a run the sweeper recovers after a
crash, can reach the gateway after the token's TTL. The gateway refuses it as expired; this mints a fresh token for
the same thread, step, tool, input hash and approvers, but only from approvals recorded for that exact input and
younger than `approval_renewal_max_age_seconds`. Anything else returns None and the call needs a fresh review.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ops_policy import TokenError
from ops_policy.approval import Binding, binding_of, mint_approval
from ops_service_kit.logging import get_logger

from ..store.reviews import ReviewStore
from .deps import Runtime
from .runs import graph_store

log = get_logger("ops_agents.api.approval_renewal")


class ApprovalRenewal:
    def __init__(self, rt: Runtime) -> None:
        self.rt = rt

    async def renew(self, token: str) -> str | None:
        key = self.rt.settings.review_key.get_secret_value()
        try:
            binding = binding_of(token, key)
        except (TokenError, KeyError, ValueError):
            return None
        rows = await ReviewStore(graph_store(self.rt).engine).approvals_of_input(
            binding.thread, binding.step, binding.inputHash
        )
        recorded = {approver for approver, _ in rows}
        if not binding.approvers or not set(binding.approvers) <= recorded:
            return None  # an approval was withdrawn or replaced by one of a different input
        oldest = min(
            datetime.fromisoformat(at.replace("Z", "+00:00")) for approver, at in rows if approver in binding.approvers
        )
        max_age = timedelta(seconds=self.rt.settings.approval_renewal_max_age_seconds)
        if datetime.now(UTC) - oldest > max_age:
            log.info("approval_renewal_refused", thread=binding.thread, step=binding.step, reason="too_old")
            return None
        log.info("approval_renewed", thread=binding.thread, step=binding.step)
        fresh = Binding(binding.thread, binding.step, binding.tool, binding.inputHash, list(binding.approvers))
        return mint_approval(fresh, key, ttl_s=self.rt.settings.review_token_ttl_seconds)
