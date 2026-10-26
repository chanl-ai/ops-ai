"""Which tools the gateway knows, their access class and how each runs. The class comes from here, never from the
caller, so a write cannot be passed off as a read.

With a module store the tool-module registry is the one source: a tool is an operation of a module, and a tool no
module holds is unknown. Without one (the agents-service gateway tests) the agents catalogue answers, as before."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from ops_agents.activities.catalog import Catalog

from .modules.seed import PLATFORM_TOOLS, SENDS, ensure_platform_tools
from .modules.seed import WORKFLOW_TOOLS as PLATFORM_MODULE_TOOLS
from .store.modules import Aggregate, ModuleStore, served_operations

WRITES = {"write"}
JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array"}

# Workflow tools that are not in the agent catalogue: their access and whether a write waits for approval. send_reply
# emails a customer, so it is a write that waits; the platform's own tools come from their one declaration.
WORKFLOW_TOOLS: dict[str, tuple[str, bool]] = {name: ("write", waits) for name, (_, waits) in SENDS.items()} | {
    str(t["name"]): (str(t["access"]), bool(t["requires_approval"])) for t in PLATFORM_TOOLS
}


# Platform tools only a system workflow calls: kept out of every module's operations (seed.runtime_module).
SYSTEM_ONLY = frozenset(str(t["name"]) for t in PLATFORM_TOOLS if t.get("system"))


def approval_policy(module: Aggregate, op: dict[str, Any]) -> dict[str, Any]:
    """How a write to `op` is approved, as the gateway, OPA and the review service read it: `approvers` distinct people
    from `approverTeam`, and whether approving asks for a step-up (`stepUp`): set on the operation, or implied by two
    approvers. Whether the person who asked may approve is the tenant's `requesterMayDecide` policy (c-186)."""
    approvers = int(op.get("approvers") or 1)
    return {
        "approvers": approvers,
        "approver_team": op.get("approver_team") or module["team_id"],
        "step_up": bool(op.get("step_up")) or approvers > 1,
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
        if f.get("default") is not None:
            prop["default"] = f["default"]
        props[f["name"]] = prop
    required = [f["name"] for f in fields if f.get("required")]
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


def inferred(value: Any) -> dict[str, Any]:
    """An open JSON Schema for an example value: its keys and their nesting, nothing about which are required."""
    if isinstance(value, dict):
        return {"type": "object", "properties": {str(k): inferred(v) for k, v in cast(dict[Any, Any], value).items()}}
    if isinstance(value, list):
        items = cast(list[Any], value)
        return {"type": "array", "items": inferred(items[0]) if items else {}}
    return {}


@dataclass(frozen=True)
class Resolved:
    """A tool the gateway may run: its access class, how it runs (`local`, `stub` or `http`), and, from the registry,
    the module and operation it is."""

    access: str
    executor: str
    module: Aggregate | None = None
    operation: dict[str, Any] | None = None


class ToolRegistry:
    def __init__(self, catalog: Catalog, modules: ModuleStore | None = None) -> None:
        """Serves every tenant: each lookup names the tenant of the caller it is for. The Platform tools module the
        registry writes for a tenant that has none belongs to no team (c-433)."""
        self.catalog = catalog
        self.modules = modules
        # Tenants whose platform tools this process has made sure of; a restart checks again, which writes nothing.
        self._platform_checked: set[str] = set()

    async def _platform_tools(self, tenant_id: str) -> None:
        if self.modules is None or tenant_id in self._platform_checked:
            return
        await ensure_platform_tools(self.modules, tenant_id=tenant_id, at=datetime.now(UTC))
        self._platform_checked.add(tenant_id)

    def access(self, tool: str) -> str:
        """The agents catalogue's class; `resolve` is what the gateway decides by."""
        if tool in WORKFLOW_TOOLS:
            return WORKFLOW_TOOLS[tool][0]
        definition = self.catalog.tool(tool)
        return definition.access if definition else "unknown"

    async def grantable(self, tenant_id: str, sees: Callable[[Aggregate], bool] | None = None) -> list[dict[str, Any]]:
        """The operations an agent may be granted: every enabled operation of a published module that has not drifted,
        the same conditions `/v1/calls` checks before it runs one. Without a module store, the agents catalogue.
        `sees` keeps the modules one team sees (the MCP adapter lists a team's tools, c-356)."""
        if self.modules is None:
            return [
                {
                    "name": t.name,
                    "description": t.description,
                    "access": t.access,
                    "input_schema": t.input_schema,
                    "requires_approval": t.access in WRITES and t.requires_approval is not False,
                    "approvers": t.approvers,
                    "step_up": t.approvers > 1,
                    "output_shape": None,
                    "module_id": None,
                    "module_name": t.server,
                }
                for t in self.catalog.tools
            ]
        await self._platform_tools(tenant_id)
        rows: list[dict[str, Any]] = []
        # A person's grant list reads their team's modules; another service's, every team's (`all_teams`).
        modules = await (self.modules.all(tenant_id) if sees is not None else self.modules.all_teams(tenant_id))
        for module in modules:
            if module["status"] != "published" or module["drift"] or (sees is not None and not sees(module)):
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
                        "requires_approval": bool(op["requires_approval"]),
                        "approvers": approval_policy(module, op)["approvers"],
                        "step_up": approval_policy(module, op)["step_up"],
                        "output_shape": op.get("output_shape"),
                        "module_id": module["id"],
                        "module_name": module["display_name"],
                    }
                )
        return sorted(rows, key=lambda r: (r["module_name"], r["name"]))

    async def access_for(self, tool: str, tenant_id: str, team_id: str | None = None) -> str:
        """The class the gateway decides `tool` by for the tenant: the registry's operation, else a workflow tool."""
        return self._access(tool, await self.resolve(tool, tenant_id=tenant_id, team_id=team_id))

    async def described(
        self, tool: str, tenant_id: str, team_id: str | None = None
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None]:
        """access_for, policy_for and output_schema_for of `tool`, from one resolve: a review list asks this once per
        tool, and resolving three times read the tool's module three times (c-451)."""
        resolved = await self.resolve(tool, tenant_id=tenant_id, team_id=team_id)
        return self._access(tool, resolved), self._policy(tool, resolved), self._output(resolved)

    @staticmethod
    def _access(tool: str, resolved: Resolved | None) -> str:
        if resolved is not None:
            return resolved.access
        return WORKFLOW_TOOLS.get(tool, ("unknown", True))[0]

    async def requires_approval(self, tool: str, tenant_id: str, team_id: str | None = None) -> bool:
        """Whether a write to `tool` waits for a person's approval, from its registry entry alone: the operation's own
        flag, else the workflow tool's or the agents catalogue's declaration. A write that declares nothing waits."""
        resolved = await self.resolve(tool, tenant_id=tenant_id, team_id=team_id)
        if resolved is not None and resolved.operation is not None:
            return bool(resolved.operation["requires_approval"])
        if tool in WORKFLOW_TOOLS:
            return WORKFLOW_TOOLS[tool][1]
        definition = self.catalog.tool(tool)
        return definition is None or definition.requires_approval is not False

    async def policy_for(self, tool: str, tenant_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        """The write approval policy of the tenant's operation `tool`; without a module store, the agents catalogue's
        (its `approvers`, no particular team). None for a tool neither holds."""
        if self.modules is None:
            return self._policy(tool, None)
        return self._policy(tool, await self.resolve(tool, tenant_id=tenant_id, team_id=team_id))

    def _policy(self, tool: str, resolved: Resolved | None) -> dict[str, Any] | None:
        if self.modules is None:
            definition = self.catalog.tool(tool)
            if definition is None:
                return None
            return {
                "approvers": definition.approvers,
                "approver_team": None,
                "step_up": definition.approvers > 1,
            }
        if resolved is None or resolved.module is None or resolved.operation is None:
            return None
        return approval_policy(resolved.module, resolved.operation)

    async def output_schema_for(self, tool: str, tenant_id: str, team_id: str | None = None) -> dict[str, Any] | None:
        """The shape of what the tenant's operation `tool` answers (c-353): its imported response schema, else one
        inferred from its example response (open, since an example may leave fields out), else None."""
        if self.modules is None:
            return None
        return self._output(await self.resolve(tool, tenant_id=tenant_id, team_id=team_id))

    def _output(self, resolved: Resolved | None) -> dict[str, Any] | None:
        if self.modules is None or resolved is None or resolved.operation is None:
            return None
        op = resolved.operation
        if isinstance(op.get("response_schema"), dict) and op["response_schema"]:
            return cast(dict[str, Any], op["response_schema"])
        stub = op.get("stub")
        # {"ok": true} is the stub an import writes when the document gives no example.
        return inferred(stub) if stub not in (None, {"ok": True}) else None

    async def resolve(self, tool: str, *, tenant_id: str, team_id: str | None = None) -> Resolved | None:
        if self.modules is None:
            access = self.access(tool)
            return None if access == "unknown" else Resolved(access, "local")
        # The calling service's tenant, from its service token; the team from the run or the person.
        found = await self.modules.operation_named(tenant_id, tool, team_id)
        if found is None and tool in PLATFORM_MODULE_TOOLS:
            await self._platform_tools(tenant_id)
            found = await self.modules.operation_named(tenant_id, tool, team_id)
        if found is None:
            # A system tool (c-257) is no module's operation, so no agent can be granted it; it resolves as the
            # platform's own, and the gateway runs it only for its system workflow.
            return Resolved(WORKFLOW_TOOLS[tool][0], "local") if tool in SYSTEM_ONLY else None
        module, op = found
        return Resolved(op["access"], op["executor"], module, op)
