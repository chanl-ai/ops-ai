"""The workflows tools-service governs calls for, read from agents-service, which owns them (c-039).

`AgentsWorkflows` asks agents-service's internal route with this service's Ed25519 token for the caller's tenant and
keeps each tenant's answer for a short while, so a module page does not cost one request per approval. When
agents-service cannot answer, every path that needs a workflow refuses with 503 instead of guessing: a fixture or an
empty list would let an approval be refused, or accepted, on data that is not there.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ops_service_kit.errors import ServiceUnavailable


@dataclass(frozen=True)
class WorkflowRef:
    id: str
    name: str
    owner: str
    team_id: str
    status: str


class WorkflowDirectory(Protocol):
    async def all(self, tenant_id: str) -> dict[str, WorkflowRef]: ...


def _refs(rows: Iterable[dict[str, Any]]) -> dict[str, WorkflowRef]:
    return {
        str(r["id"]): WorkflowRef(
            str(r["id"]), str(r["name"]), str(r["owner"]), str(r["teamId"]), str(r.get("status", "live"))
        )
        for r in rows
    }


class AgentsWorkflows:
    def __init__(
        self,
        client: httpx.AsyncClient,
        token: Callable[[str], str],
        *,
        ttl_s: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`client` is based at agents-service; `token(tenant)` mints this service's token for audience "agents"."""
        self.client, self.token, self.ttl_s, self.clock = client, token, ttl_s, clock
        self._cache: dict[str, tuple[float, dict[str, WorkflowRef]]] = {}

    async def all(self, tenant_id: str) -> dict[str, WorkflowRef]:
        now = self.clock()
        kept = self._cache.get(tenant_id)
        if kept is not None and kept[0] > now:
            return kept[1]
        try:
            r = await self.client.get(
                "/v1/internal/workflows", headers={"Authorization": f"Bearer {self.token(tenant_id)}"}
            )
            r.raise_for_status()
            found = _refs(r.json()["data"])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise ServiceUnavailable(
                "agents-service did not answer the workflow list, so no workflow can be checked; try again shortly.",
                code="workflows_unavailable",
            ) from e
        self._cache[tenant_id] = (now + self.ttl_s, found)
        return found


class StaticWorkflows:
    """A fixed list, for tests and for a tools-service run without agents-service configured."""

    def __init__(self, rows: Iterable[dict[str, Any]] = ()) -> None:
        self.rows = _refs(rows)

    async def all(self, tenant_id: str) -> dict[str, WorkflowRef]:
        return self.rows
