"""Renewing an approval token that expired between the decision and the call (durability-failure-and-audit.md).

A decision is resumed at once, but a resume retried after its lease was busy, or a run the sweeper recovers after a
crash, can reach the gateway after the token's TTL. The gateway refuses it as expired; this asks the gateway for a
fresh token for the same thread, step, tool and input, named for the approvals recorded for that exact input while they
are younger than `approval_renewal_max_age_seconds`. The ask is rebuilt from the call and the review rows, never from
the expired token, whose claims agents cannot verify. Anything else returns None and the call needs a fresh review.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ops_identity import ServiceCallError
from ops_policy import input_hash
from ops_service_kit.http import Json
from ops_service_kit.logging import get_logger

from ..activities.gateway import ApprovalAsk, TokenMinter, current_run_context
from ..store.reviews import ReviewStore
from .deps import Runtime
from .runs import graph_store

log = get_logger("ops_agents.api.approval_renewal")


class ApprovalRenewal:
    def __init__(self, rt: Runtime, gateway: TokenMinter) -> None:
        self.rt = rt
        self.gateway = gateway

    async def renew(self, tool: str, arguments: Json, *, key: str) -> str | None:
        thread, digest = current_run_context().thread, input_hash(arguments)
        if not thread:
            return None
        rows = await ReviewStore(graph_store(self.rt).engine).approvals_of_input(thread, key, digest)
        if not rows:
            return None  # an approval was withdrawn or replaced by one of a different input
        oldest = min(datetime.fromisoformat(at.replace("Z", "+00:00")) for _, at in rows)
        max_age = timedelta(seconds=self.rt.settings.approval_renewal_max_age_seconds)
        if datetime.now(UTC) - oldest > max_age:
            log.info("approval_renewal_refused", thread=thread, step=key, reason="too_old")
            return None
        ask = ApprovalAsk(thread, key, tool, arguments, digest, tuple(sorted({a for a, _ in rows})))
        try:
            token = await self.gateway.approval(ask)
        except ServiceCallError as e:
            log.info("approval_renewal_refused", thread=thread, step=key, reason=e.code)
            return None
        log.info("approval_renewed", thread=thread, step=key)
        return token
