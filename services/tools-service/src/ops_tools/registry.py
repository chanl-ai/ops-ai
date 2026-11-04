"""Which tools the gateway knows, their access class and how each runs. The class comes from here, never from the
caller, so a write cannot be passed off as a read.

With a module store the tool-module registry is the one source: a tool is an operation of a module, and a tool no
module holds is unknown. Without one (the agents-service gateway tests) the agents catalogue answers, as before."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from ops_agents.activities.catalog import Catalog
from ops_store.team_scope import acting_team

from .connections.records import account_for
from .defaults import ensure_defaults
from .modules.seed import PLATFORM_TOOLS, READ_TOOLS, SENDS, ensure_platform_tools, tool_title
from .modules.seed import WORKFLOW_TOOLS as PLATFORM_MODULE_TOOLS
from .store.connections import ConnectionStore
from .store.modules import Aggregate, ModuleStore, served_operations
from .store.team_defaults import TeamDefaults

if TYPE_CHECKING:
    from .plugins.host import PluginHost

WRITES = {"write"}
JSON_TYPES = {"string", "number", "integer", "boolean", "object", "array"}

# Workflow tools that are not in the agent catalogue: their access and whether a write waits for approval. send_reply
# emails a customer, so it is a write that waits; the platform's own tools come from their one declaration.
WORKFLOW_TOOLS: dict[str, tuple[str, bool]] = {name: ("write", waits) for name, (_, waits) in SENDS.items()} | {
    str(t["name"]): (str(t["access"]), bool(t["requires_approval"])) for t in [*PLATFORM_TOOLS, *READ_TOOLS]
}


# Platform tools only a system workflow calls: kept out of every module's operations (seed.runtime_module).
SYSTEM_ONLY = frozenset(str(t["name"]) for t in PLATFORM_TOOLS if t.get("system"))


def approval_policy(module: Aggregate, op: dict[str, Any]) -> dict[str, Any]:
    """How a write to `op` is approved, as the gateway, OPA and the review service read it: `approvers` distinct people
    from `approverTeam`, and whether approving asks for a step-up (`stepUp`): set on the operation, or implied by two
    approvers. Whether the person who asked may approve is the tenant's `requesterMayDecide` policy."""
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
    def __init__(
        self,
        catalog: Catalog,
        modules: ModuleStore | None = None,
        plugins: PluginHost | None = None,
        connections: ConnectionStore | None = None,
    ) -> None:
        """Serves every tenant: each lookup names the tenant of the caller it is for. The Platform tools module the
        registry writes for a tenant that has none belongs to no team. `connections` is read for the
        account a module's call signs in with."""
        self.catalog = catalog
        self.modules = modules
        self.connections = connections
        # The installed plugins: each one's module, seen and called through the calling team's binding.
        self.plugins = plugins
        # Teams whose platform tools this process has made sure of, by tenant; a restart checks again, which writes
        # nothing. Per team: a tool one team holds in its own module (the Platform team's mail module) is not another
        # team's, so a check made for one team says nothing about the next.
        self._platform_checked: set[tuple[str, str | None]] = set()

    async def _platform_tools(self, tenant_id: str, team_id: str | None = None) -> None:
        team = team_id if team_id is not None else acting_team()
        if self.modules is None or (tenant_id, team) in self._platform_checked:
            return
        now = datetime.now(UTC)
        if team:
            # The team's defaults on its first lookup in this process, until the team-created event
            # provisions a new team; a team already current writes nothing. Before the platform module, so a tool the
            # team's own built-in copy holds is not added there too.
            await ensure_defaults(
                self.modules, TeamDefaults(self.modules.engine), tenant_id=tenant_id, team_id=team, at=now
            )
        await ensure_platform_tools(self.modules, tenant_id=tenant_id, team_id=team, at=now)
        self._platform_checked.add((tenant_id, team))

    def access(self, tool: str) -> str:
        """The agents catalogue's class; `resolve` is what the gateway decides by."""
        if tool in WORKFLOW_TOOLS:
            return WORKFLOW_TOOLS[tool][0]
        definition = self.catalog.tool(tool)
        return definition.access if definition else "unknown"

    async def grantable(self, tenant_id: str, sees: Callable[[Aggregate], bool] | None = None) -> list[dict[str, Any]]:
        """The operations an agent may be granted: every enabled operation of a published module that has not drifted,
        the same conditions `/v1/calls` checks before it runs one. Without a module store, the agents catalogue.
        `sees` keeps the modules one team sees (the MCP adapter lists a team's tools)."""
        if self.modules is None:
            return [
                {
                    "name": t.name,
                    "title": None,
                    "description": t.description,
                    "access": t.access,
                    "input_schema": t.input_schema,
                    # Off unless the tool declares it (approvals are off by default).
                    "requires_approval": t.access in WRITES and t.requires_approval is True,
                    "approvers": t.approvers,
                    "step_up": t.approvers > 1,
                    "output_shape": None,
                    "module_id": None,
                    "module_name": t.server,
                }
                for t in self.catalog.tools
            ]
        await self._platform_tools(tenant_id)
        if self.plugins is not None:
            await self.plugins.ensure(tenant_id, datetime.now(UTC))
        rows: list[dict[str, Any]] = []
        # A person's grant list reads their team's modules; another service's, every team's (`all_teams`).
        modules = await (self.modules.all(tenant_id) if sees is not None else self.modules.all_teams(tenant_id))
        # A tool the acting team holds in a module of its own (its built-in copy) is the one a call resolves to,
        # so the workspace-level module's operation of that name is not offered beside it.
        team = acting_team()
        own = {str(o["name"]) for m in modules if team and m["team_id"] == team for o in m["operations"]}
        for module in modules:
            if module["status"] != "published" or module["drift"] or (sees is not None and not sees(module)):
                continue
            # With no plugin installed, a module a plugin left from an earlier start is listed to nobody, as the
            # gateway refuses its every call.
            if self.plugins is None and str(module.get("template_id") or "").startswith("plugin:"):
                continue
            if self.plugins is not None and not await self.plugins.visible(tenant_id, acting_team(), module):
                continue
            # A plugin's tools as the acting team's version declares them, so the list offers what a call
            # allows: a tool only a newer version has is not offered, and one the team's version keeps stays listed.
            view = module
            if (
                self.plugins is not None
                and self.plugins.versions
                and str(module.get("template_id") or "").startswith("plugin:")
            ):
                view = await self.plugins.for_call(tenant_id, acting_team(), module, "production")
            for served in served_operations(module):
                op = self.plugins.operation(view, served) if view is not module and self.plugins is not None else served
                if not op["enabled"] or (module["team_id"] is None and op["name"] in own):
                    continue
                rows.append(
                    {
                        "name": op["name"],
                        # What people see in place of the name, a built-in or plugin tool's; a team's own has none.
                        "title": tool_title(module, op["name"], self.plugins.title_of if self.plugins else None),
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
    ) -> tuple[str, dict[str, Any] | None, dict[str, Any] | None, float | None]:
        """access_for, policy_for, output_schema_for and the deadline of `tool`, from one resolve: a review list asks
        this once per tool, and resolving three times read the tool's module three times."""
        resolved = await self.resolve(tool, tenant_id=tenant_id, team_id=team_id)
        return (
            self._access(tool, resolved),
            self._policy(tool, resolved),
            self._output(resolved),
            self.deadline(resolved),
        )

    @staticmethod
    def _access(tool: str, resolved: Resolved | None) -> str:
        if resolved is not None:
            return resolved.access
        return WORKFLOW_TOOLS.get(tool, ("unknown", True))[0]

    @staticmethod
    def deadline(resolved: Resolved | None) -> float | None:
        """How long the gateway may take over one call of the operation, in seconds: a code operation's run limit and
        the runner's margin, else the operation's or module's timeout and a margin for signing in and the egress check.
        The engine's step waits at least this long before it calls a write uncertain."""
        if resolved is None or resolved.operation is None or resolved.module is None:
            return None
        op, module = resolved.operation, resolved.module
        if op.get("executor") == "code":
            limits = cast(dict[str, Any], cast(dict[str, Any], op.get("code") or {}).get("limits") or {})
            return float(limits.get("timeS", 10)) + 15.0
        limit_ms = op.get("timeout_ms") or module.get("timeout_ms")
        return float(limit_ms) / 1000 + 5.0 if limit_ms else None

    async def requires_approval(self, tool: str, tenant_id: str, team_id: str | None = None) -> bool:
        """Whether a write to `tool` waits for a person's approval, from its registry entry alone: the operation's own
        flag, else the workflow tool's or the agents catalogue's declaration. A write that declares nothing runs:
        approvals are off by default and a team turns them on in its policies."""
        resolved = await self.resolve(tool, tenant_id=tenant_id, team_id=team_id)
        if resolved is not None and resolved.operation is not None:
            return bool(resolved.operation["requires_approval"])
        if tool in WORKFLOW_TOOLS:
            return WORKFLOW_TOOLS[tool][1]
        definition = self.catalog.tool(tool)
        return definition is not None and definition.requires_approval is True

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
        """The shape of what the tenant's operation `tool` answers: its imported response schema, else one
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

    async def resolve(
        self,
        tool: str,
        *,
        tenant_id: str,
        team_id: str | None = None,
        run: str = "production",
        account: str | None = None,
        person: str | None = None,
    ) -> Resolved | None:
        """`run` is the kind of run the call is made in (test or production). The module comes back with the account
        its call signs in with (`connection_id`, from connections.records.account_for, and whether it is a `sandbox`),
        which picks its address, instance and hosts; a listing or an access check, which shows the same tools either
        way, takes production's.
        `account` names one of the team's accounts of the plugin's app for the call; none uses `person`'s
        default account, else the team's."""
        if self.modules is None:
            access = self.access(tool)
            return None if access == "unknown" else Resolved(access, "local")
        # The calling service's tenant, from its service token; the team from the run or the person.
        if self.plugins is not None:
            await self.plugins.ensure(tenant_id, datetime.now(UTC))
        found = await self.modules.operation_named(tenant_id, tool, team_id)
        if found is None and tool in PLATFORM_MODULE_TOOLS:
            await self._platform_tools(tenant_id, team_id)
            found = await self.modules.operation_named(tenant_id, tool, team_id)
        if found is None:
            # A system tool is no module's operation, so no agent can be granted it; it resolves as the
            # platform's own, and the gateway runs it only for its system workflow.
            return Resolved(WORKFLOW_TOOLS[tool][0], "local") if tool in SYSTEM_ONLY else None
        module, op = found
        if (
            self.plugins is not None
            and module.get("template_id", "")
            and str(module["template_id"]).startswith("plugin:")
        ):
            # One binding lookup per call: the team's connection, endpoint and egress hosts, and a rate window
            # of the team's own, since windows are kept per tenant and operation.
            team = team_id if team_id is not None else acting_team()
            module = await self.plugins.for_call(tenant_id, team, module, run, account=account, person=person)
            op = {**self.plugins.operation(module, op), "rate_key": f"{op['name']}@{team}"}
        else:
            conn = (
                await self.connections.get(tenant_id, str(module["connection_id"]))
                if self.connections is not None and module.get("connection_id")
                else None
            )
            if conn is not None and self.connections is not None:
                # A test run takes the app's sandbox account when the team has one (records.account_for).
                found = await self.connections.accounts(tenant_id, str(conn["team_id"]), str(conn["app_id"]))
                conn = account_for(conn, found, run) or conn
                module = {**module, "connection_id": conn["id"]}
            module = {**module, "sandbox": bool((conn or {}).get("sandbox"))}
        return Resolved(op["access"], op["executor"], module, op)
