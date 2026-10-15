"""Which tools the gateway knows, their access class and how each runs. The class comes from here, never from the
caller, so a write cannot be passed off as a read.

With a module store the tool-module registry is the one source: a tool is an operation of a module, and a tool no
module holds is unknown. Without one (the agents-service gateway tests) the agents catalogue answers, as before."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ops_agents.activities.catalog import Catalog

from .store.modules import Aggregate, ModuleStore, served_operations

WRITES = {"write"}
JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array"}

# Workflow tools that are not in the agent catalogue. send_reply emails a customer, so it is a write.
WORKFLOW_TOOLS = {"send_reply": "write"}


def approval_policy(module: Aggregate, op: dict[str, Any]) -> dict[str, Any]:
    """How a write to `op` is approved, as the gateway, OPA and the review service read it: `approvers` distinct people
    from `approverTeam`, and whether the person who asked may be one (`selfApproval`)."""
    approvers = int(op.get("approvers") or 1)
    return {
        "approvers": approvers,
        "approver_team": op.get("approver_team") or module["team_id"],
        "self_approval": bool(op.get("self_approval")),
    }


def input_schema(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """An operation's input fields as the JSON Schema a model is handed. Unknown arguments are refused at the gateway
    (`invalid_fields`), so the schema says so too."""
    props: dict[str, Any] = {}
    for f in fields:
        prop: dict[str, Any] = {"type": f["type"] if f["type"] in JSON_TYPES else "string"}
        if f.get("description"):
            prop["description"] = f["description"]
        if f.get("enum"):
            prop["enum"] = list(f["enum"])
        if f.get("example") is not None:
            prop["examples"] = [f["example"]]
        props[f["name"]] = prop
    required = [f["name"] for f in fields if f.get("required")]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


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

    async def grantable(self, tenant_id: str) -> list[dict[str, Any]]:
        """The operations an agent may be granted: every enabled operation of a published module that has not drifted,
        the same conditions `/v1/calls` checks before it runs one. Without a module store, the agents catalogue."""
        if self.modules is None:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "access": t.access,
                    "input_schema": t.input_schema,
                    "requires_approval": t.access in WRITES,
                    "approvers": t.approvers,
                    "module_id": None,
                    "module_name": t.server,
                }
                for t in self.catalog.tools
            ]
        rows: list[dict[str, Any]] = []
        for module in await self.modules.all(tenant_id):
            if module["status"] != "published" or module["drift"]:
                continue
            for op in served_operations(module):
                if not op["enabled"]:
                    continue
                rows.append(
                    {
                        "name": op["name"],
                        "description": op["description"],
                        "access": op["access"],
                        "input_schema": input_schema(op["input"]),
                        "requires_approval": op["access"] in WRITES or bool(op["requires_approval"]),
                        "approvers": approval_policy(module, op)["approvers"],
                        "module_id": module["id"],
                        "module_name": module["display_name"],
                    }
                )
        return sorted(rows, key=lambda r: (r["module_name"], r["name"]))

    async def access_for(self, tool: str, tenant_id: str) -> str:
        """The class the gateway decides `tool` by for the tenant: the registry's operation, else a workflow tool."""
        resolved = await self.resolve(tool, tenant_id=tenant_id)
        if resolved is not None:
            return resolved.access
        return WORKFLOW_TOOLS.get(tool, "unknown")

    async def policy_for(self, tool: str, tenant_id: str) -> dict[str, Any] | None:
        """The write approval policy of the tenant's operation `tool`; without a module store, the agents catalogue's
        (its `approvers`, no particular team). None for a tool neither holds."""
        if self.modules is None:
            definition = self.catalog.tool(tool)
            if definition is None:
                return None
            return {"approvers": definition.approvers, "approver_team": None, "self_approval": False}
        resolved = await self.resolve(tool, tenant_id=tenant_id)
        if resolved is None or resolved.module is None or resolved.operation is None:
            return None
        return approval_policy(resolved.module, resolved.operation)

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
