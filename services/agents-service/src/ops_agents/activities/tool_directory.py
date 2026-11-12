"""The tools an agent may be granted, and the grants a run hands the model. tools-service's registry is the one
source: an agent is granted published operations by name, and a run gets each one's description and input schema
from there, so a tool imported and published in tools-service reaches the agent picker and the run with no copy here.

`ToolsOperations` asks tools-service (GET /v1/grantable-operations) with a service token holding `tools:view` and naming
the tenant of the request or run, and keeps each tenant's answer for `ttl_s`; when tools-service cannot answer it
refuses (503) rather than serve a list nobody vouched for. `CatalogTools` serves the fixture catalogue, for runs with no
gateway (unit tests); it is never what a stack with tools-service runs on.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from ops_access import tool_waits
from ops_agent_kernel.types import Access, ToolGrant
from ops_identity import (
    ACTING_FOR_HEADER,
    ActingForTokens,
    ServiceCallError,
    ServiceClient,
    ServiceUnreachable,
    segment,
)
from ops_service_kit.errors import ApiError

from ..store.tenancy import current_team, current_tenant
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
    # The operation's declared result shape (`x-ops-shape`), for the shaper; None when it declares none.
    output_shape: str | None = None
    # Approving a call asks for a step-up: set on the operation, or two approvers.
    step_up: bool = False
    # What people see in place of the name: a plugin tool's manifest title; None for any other tool.
    title: str | None = None
    # The team has a test account of the app, so a test turn's write changes nothing real and never asks.
    test_account: bool = False
    # False for a tool the team turned off in its app's catalog (ToolsOperations.off_operations).
    added: bool = True
    # Who answers a write that waits, from tools-service's one resolver: "person" (the asker confirms in the chat) or
    # "reviewer" (someone holding `reviewer_role`). A row that names none is the person.
    answer: str = "person"
    reviewer_role: str | None = None

    def grant(self) -> ToolGrant:
        return ToolGrant(
            self.name,
            self.module_name,
            self.description,
            cast(Access, self.access),
            self.input_schema,
            self.requires_approval,
        )


class ToolDirectory(Protocol):
    async def operations(self) -> list[OperationRef]:
        """The grantable operations of the current tenant (store/tenancy.py)."""
        ...


async def grants_for(directory: ToolDirectory, names: list[str]) -> list[ToolGrant]:
    """Grants for the tool names an agent holds that the registry still offers; `workflow:` names are offered by the
    workflow runner, and a name the registry no longer has (hidden, unpublished, drifted) is not handed to the model."""
    wanted = [n for n in names if not n.startswith(("workflow:", "agent:"))]
    if not wanted:
        return []
    by_name = {o.name: o for o in await directory.operations()}
    # A tool the team turned off in its app's catalog still reaches the run, so a call to it is refused with the fix
    # (gateway TOOL_NOT_ADDED, drawn as a card) instead of the agent not knowing the tool exists.
    off = {o.name: o for o in await off_operations(directory)}
    # A name the kept list lacks may be a tool published since it was read (the agent was granted it and published
    # moments ago): ask tools-service once more before leaving it out of the turn.
    if any(n not in by_name for n in wanted) and (forget := getattr(directory, "forget", None)) is not None:
        forget()
        by_name = {o.name: o for o in await directory.operations()}
    return [(by_name.get(n) or off[n]).grant() for n in wanted if n in by_name or n in off]


async def off_operations(directory: ToolDirectory) -> list[OperationRef]:
    """The operations the team turned off in its app's catalog, for a directory that keeps them; none otherwise."""
    listed = getattr(directory, "off_operations", None)
    return list(await listed()) if listed is not None else []


class ToolsOperations:
    def __init__(self, tools: ServiceClient, *, ttl_s: float = 30, clock: Callable[[], float] = time.monotonic) -> None:
        """`tools` calls tools-service as this service for the current tenant (api/app.py)."""
        self.tools = tools
        self.ttl_s = ttl_s
        self.clock = clock
        # Per tenant and team: a team's appChanges and appChangesByApp change which of its writes wait (tools-service).
        self._cache: dict[tuple[str, str | None], tuple[float, list[OperationRef]]] = {}

    async def operations(self) -> list[OperationRef]:
        """The operations agents may be granted and offered: those the team has added."""
        return [o for o in await self._listed() if o.added]

    async def off_operations(self) -> list[OperationRef]:
        """The operations the team turned off in its app's catalog: never offered, only handed to a run that holds
        one, so its call is refused with the fix."""
        return [o for o in await self._listed() if not o.added]

    async def _listed(self) -> list[OperationRef]:
        key = (current_tenant(), current_team())
        hit = self._cache.get(key)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        try:
            rows = cast(list[dict[str, Any]], await self.tools.get("/v1/grantable-operations"))
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ToolsUnavailable(
                "The tools service cannot be reached, so the tools agents may use are unknown. Try again shortly."
            ) from e
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
                output_shape=o.get("outputShape"),
                step_up=bool(o.get("stepUp")) or int(o.get("approvers") or 1) > 1,
                title=o.get("title"),
                test_account=bool(o.get("testAccount")),
                added=o.get("added") is not False,
                answer=str(o.get("answer") or "person"),
                reviewer_role=o.get("reviewerRole"),
            )
            for o in rows
        ]
        self._cache[key] = (self.clock(), refs)
        return refs

    def forget(self) -> None:
        """Drops the current tenant and team's kept list, so the next read asks again (a tool offered moments ago)."""
        self.forget_for(current_tenant(), current_team())

    def forget_for(self, tenant: str, team: str | None) -> None:
        """Drops one team's kept list, for a change heard from platform-service (the team's approval answers)."""
        self._cache.pop((tenant, team), None)


class CatalogTools:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog

    def forget(self) -> None:
        """The catalogue is read from files at start, so there is nothing kept to drop."""

    async def operations(self) -> list[OperationRef]:
        return [
            OperationRef(
                name=t.name,
                description=t.description,
                access=t.access,
                input_schema=t.input_schema,
                requires_approval=tool_waits(t.access, t.approval_mode),
                module_id=None,
                module_name=t.server,
                approvers=t.approvers,
                step_up=t.step_up or t.approvers > 1,
            )
            for t in self.catalog.tools
        ]


class AppStates(Protocol):
    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        """`team`'s apps as tools-service lists them, each card's state read for `person` (an email) when given."""
        ...

    async def accounts(
        self, person: str | None, team: str | None, app_id: str, *, usable: bool = False, name: str | None = None
    ) -> list[dict[str, Any]]:
        """The accounts of `app_id` a call may name (`GET /v1/apps/{app}/accounts`): with `usable`, the team's live
        accounts a step or an agent names; with `person`, also that person's own; with `name`, the one so named. The
        names are compared there, never here."""
        ...


class ToolsApps:
    """The team's apps from tools-service's `GET /v1/apps`, built-in ones included, for the Tools page: which app a
    tool set belongs to and whether it is connected. Asked for the person who lists the tools (acting for them), so an
    app each person signs in to reads as theirs. `tools` holds connections:view, claimed only on this read."""

    def __init__(self, tools: ServiceClient, people: ActingForTokens | None) -> None:
        self.tools = tools
        self.people = people

    async def cards(self, person: str | None, team: str | None) -> list[dict[str, Any]]:
        team = team or current_team()
        if not team:
            return []
        headers: dict[str, str] = {}
        if person and self.people is not None:
            headers[ACTING_FOR_HEADER] = await self.people.token(tenant_id=current_tenant(), email=person, team_id=team)
        try:
            rows = await self.tools.get("/v1/apps", params={"include": "builtin"}, headers=headers, team=team)
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ToolsUnavailable("The tools service cannot be reached, so the tools' apps are unknown.") from e
        return cast(list[dict[str, Any]], rows)

    async def accounts(
        self, person: str | None, team: str | None, app_id: str, *, usable: bool = False, name: str | None = None
    ) -> list[dict[str, Any]]:
        team = team or current_team()
        if not team:
            return []
        headers: dict[str, str] = {}
        if person and self.people is not None:
            headers[ACTING_FOR_HEADER] = await self.people.token(tenant_id=current_tenant(), email=person, team_id=team)
        params: dict[str, str] = {**({"usable": "true"} if usable else {}), **({"mine": "true"} if person else {})}
        if name:
            params["name"] = name
        try:
            rows = await self.tools.get(
                f"/v1/apps/{segment(app_id)}/accounts", params=params, headers=headers, team=team
            )
        except ServiceCallError as e:
            if e.status == 404:
                return []
            raise ToolsUnavailable("The tools service cannot be reached, so the app's accounts are unknown.") from e
        except ServiceUnreachable as e:
            raise ToolsUnavailable("The tools service cannot be reached, so the app's accounts are unknown.") from e
        return cast(list[dict[str, Any]], rows)
