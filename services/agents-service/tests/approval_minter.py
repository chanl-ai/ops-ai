"""The gateway's approval mint as a test stands it in where no tools-service runs: it records each ask and signs it as
POST /v1/approvals does. The gateway's own checks before it mints are tools-service's tests (test_approval_routes)."""

from __future__ import annotations

from dataclasses import dataclass, field

from ops_agents.activities.gateway import ApprovalAsk
from ops_policy.approval import Binding, mint_approval

KEY = "test-gateway-review-key"


@dataclass
class GatewayMint:
    key: str = KEY
    asks: list[ApprovalAsk] = field(default_factory=list[ApprovalAsk])

    async def approval(self, ask: ApprovalAsk) -> str:
        self.asks.append(ask)
        binding = Binding(
            ask.thread,
            ask.step,
            ask.tool,
            ask.input_hash,
            list(ask.approvers),
            workflow=ask.workflow,
            system=ask.system,
        )
        return mint_approval(binding, self.key, ttl_s=300)
