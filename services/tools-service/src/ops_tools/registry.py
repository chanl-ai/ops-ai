"""Which tools the gateway knows, their access class and how each runs. The class comes from here, never from the
caller, so a write cannot be passed off as a read.

With a module store the tool-module registry is the one source: a tool is an operation of a module, and a tool no
module holds is unknown. Without one (the agents-service gateway tests) the agents catalogue answers, as before."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_agents.activities.catalog import Catalog

from .store.modules import Aggregate, ModuleStore

# Workflow tools that are not in the agent catalogue. send_reply emails a customer, so it is a write.
WORKFLOW_TOOLS = {"send_reply": "write"}


@dataclass(frozen=True)
class Resolved:
    """A tool the gateway may run: its access class, how it runs (`local`, `stub` or `http`), and, from the registry,
    the module and operation it is."""

    access: str
    executor: str
    module: Aggregate | None = None
    operation: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self, catalog: Catalog, modules: ModuleStore | None = None, *, tenant_id: str = "local") -> None:
        self.catalog = catalog
        self.modules = modules
        self.tenant_id = tenant_id

    def access(self, tool: str) -> str:
        """The agents catalogue's class; `resolve` is what the gateway decides by."""
        if tool in WORKFLOW_TOOLS:
            return WORKFLOW_TOOLS[tool]
        definition = self.catalog.tool(tool)
        return definition.access if definition else "unknown"

    async def resolve(self, tool: str, *, tenant_id: str | None = None) -> Resolved | None:
        if self.modules is None:
            access = self.access(tool)
            return None if access == "unknown" else Resolved(access, "local")
        # The calling service's tenant (from its service token); the registry's own only without one.
        found = await self.modules.operation_named(tenant_id or self.tenant_id, tool)
        if found is None:
            return None
        module, op = found
        return Resolved(op["access"], op["executor"], module, op)
