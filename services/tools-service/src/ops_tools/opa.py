"""The gateway's client for OPA's data API. OPA runs as the official container (`compose.yaml`, service `opa`)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

DECISION = "/v1/data/ops/gateway/decision"
# The id OPA's file watch gives the mounted policy (compose: /policy/gateway.rego); writing under the same id replaces
# that module instead of adding a second one with the same rules.
POLICY_ID = "policy/gateway.rego"
POLICY_FILE = Path(__file__).resolve().parents[2] / "policy" / "gateway.rego"


class PolicyMismatchError(RuntimeError):
    """OPA does not hold the policy this gateway was built with."""


def policy_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass(frozen=True)
class Decision:
    allow: bool
    reasons: list[str]


class OpaClient:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def load_review_key(self, key: str) -> None:
        """Writes the review key into OPA's data. Callers of the gateway never reach OPA, so they cannot replace it."""
        r = await self.client.put("/v1/data/ops/secrets", json={"review_key": key})
        r.raise_for_status()

    async def load_policy(self, text: str) -> None:
        """Writes the gateway's policy into OPA. OPA's own file watch can miss an edit on a bind mount and keep serving
        the old rules, so the gateway does not rely on it."""
        r = await self.client.put(f"/v1/policies/{POLICY_ID}", content=text, headers={"Content-Type": "text/plain"})
        r.raise_for_status()

    async def loaded_policy_hash(self) -> str | None:
        """The sha256 of the policy OPA is serving under POLICY_ID, or None when it holds none."""
        r = await self.client.get(f"/v1/policies/{POLICY_ID}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return policy_hash(str(r.json()["result"]["raw"]))

    async def decide(self, query: dict[str, Any]) -> Decision:
        r = await self.client.post(DECISION, json={"input": query})
        r.raise_for_status()
        result: dict[str, Any] | None = r.json().get("result")
        if result is None:
            # An undefined decision means the policy is not loaded; refuse rather than guess.
            return Decision(False, ["gateway policy is not loaded"])
        return Decision(bool(result["allow"]), list(result["reasons"]))
