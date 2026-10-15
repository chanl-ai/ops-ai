"""The tools an agent may be granted, and the grants a run hands the model. tools-service's registry is the one
source: an agent is granted published operations by name, and a run gets each one's description and input schema
from there, so a tool imported and published in tools-service reaches the agent picker and the run with no copy here.

`ToolsOperations` asks tools-service (GET /v1/internal/operations) with a service token naming the tenant of the
request or run, and keeps each tenant's answer for `ttl_s`; when tools-service cannot answer it refuses (503) rather
than serve a list nobody vouched for. `CatalogTools` serves the fixture catalogue, for runs with no gateway (unit
tests); it is never what a stack with tools-service runs on.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from ops_agent_kernel.types import Access, ToolGrant
from ops_service_kit.errors import ApiError

from ..store.tenancy import current_tenant
from .catalog import Catalog


class ToolsUnavailable(ApiError):
    status = 503
    code = "tools_unavailable"


@dataclass(frozen=True)
class OperationRef:
    name: str
    description: str
    access: str
    input_schema: dict[str, Any]
    requires_approval: bool
    module_id: str | None
    module_name: str
    approvers: int = 1

    def grant(self) -> ToolGrant:
        return ToolGrant(self.name, self.module_name, self.description, cast(Access, self.access), self.input_schema)


class ToolDirectory(Protocol):
    async def operations(self) -> list[OperationRef]:
        """The grantable operations of the current tenant (store/tenancy.py)."""
        ...


async def grants_for(directory: ToolDirectory, names: list[str]) -> list[ToolGrant]:
    """Grants for the tool names an agent holds that the registry still offers; `workflow:` names are offered by the
    workflow runner, and a name the registry no longer has (hidden, unpublished, drifted) is not handed to the model."""
    wanted = [n for n in names if not n.startswith("workflow:")]
    if not wanted:
        return []
    by_name = {o.name: o for o in await directory.operations()}
    return [by_name[n].grant() for n in wanted if n in by_name]


class ToolsOperations:
    def __init__(
        self,
        client: httpx.AsyncClient,
        token: Callable[[], str],
        *,
        ttl_s: float = 30,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`token` mints this service's token for audience "tools" naming the current tenant (api/app.py)."""
        self.client = client
        self.token = token
        self.ttl_s = ttl_s
        self.clock = clock
        self._cache: dict[str, tuple[float, list[OperationRef]]] = {}

    async def operations(self) -> list[OperationRef]:
        tenant = current_tenant()
        hit = self._cache.get(tenant)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        try:
            r = await self.client.get("/v1/internal/operations", headers={"Authorization": f"Bearer {self.token()}"})
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise ToolsUnavailable(
                "The tools service cannot be reached, so the tools agents may use are unknown. Try again shortly."
            ) from e
        rows = cast(list[dict[str, Any]], r.json()["data"])
        refs = [
            OperationRef(
                name=str(o["name"]),
                description=str(o["description"]),
                access=str(o["access"]),
                input_schema=dict(o["inputSchema"]),
                requires_approval=bool(o["requiresApproval"]),
                module_id=o.get("moduleId"),
                module_name=str(o["moduleName"]),
                approvers=int(o.get("approvers") or 1),
            )
            for o in rows
        ]
        self._cache[tenant] = (self.clock(), refs)
        return refs


class CatalogTools:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    async def operations(self) -> list[OperationRef]:
        return [
            OperationRef(
                name=t.name,
                description=t.description,
                access=t.access,
                input_schema=t.input_schema,
                requires_approval=t.access == "write",
                module_id=None,
                module_name=t.server,
                approvers=t.approvers,
            )
            for t in self.catalog.tools
        ]
