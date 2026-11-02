"""Which of a team's agents and workflows use each tool (c-609), for a plugin update's review: a person with
agents.view in their team, or a service holding `agents:view` for the team its token names.

An agent uses a tool its newest or published version grants (`toolIds`, operation names). A workflow uses it when it
runs such an agent (the agent's "used in", `used_in_all`, v1 and v2 alike) or a published v1 workflow's tool step names
it, or a v2 workflow's tool node does. Only the team's own agents and workflows are read: no team sees another's
(c-507)."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentTenantCaller
from ops_service_kit.http import Envelope, Out

from ..agent_registry import registry as agent_registry
from ..child_runs import team_workflows
from ..deps import Runtime, runtime
from ..envelope import ok
from ..workflow_registry import registry as workflow_registry
from .agents import used_in_all

router = APIRouter(prefix="/v1/tool-uses")
Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
MAX_TOOLS = 200


class ToolUser(Out):
    kind: Literal["agent", "workflow"]
    id: str
    name: str


async def tool_uses(rt: Runtime, team_id: str | None, tools: list[str]) -> dict[str, list[dict[str, str]]]:
    """For each tool name, the team's agents and workflows that use it, each `{kind, id, name}`, each once."""
    out: dict[str, list[dict[str, str]]] = {t: [] for t in tools}
    if team_id is None or not tools:
        return out

    def add(tool: str, use: dict[str, str]) -> None:
        if use not in out[tool]:
            out[tool].append(use)

    wanted = set(tools)
    reg = agent_registry(rt)
    holders: dict[str, set[str]] = {}
    for row in await reg.rows():
        if row["team_id"] != team_id:
            continue
        name, held = str(row["slug"]), set[str]()
        for n in sorted({row["version"], row["published_version"]} - {None}):
            spec: dict[str, Any] = (await reg.version(row["id"], int(n)))["spec"]
            granted = cast(list[Any], spec.get("toolIds") or [])
            held |= {str(t) for t in granted} & wanted
            name = str(spec.get("name") or name)
        for t in sorted(held):
            add(t, {"kind": "agent", "id": str(row["id"]), "name": name})
        if held:
            holders[str(row["id"])] = held
    if holders:
        runs = await used_in_all(rt)
        for agent_id, held in holders.items():
            for use in runs.get(agent_id, []):
                if not use.get("own"):
                    for t in sorted(held):
                        add(t, {"kind": "workflow", "id": str(use["workflowId"]), "name": str(use["workflowName"])})
    if rt.graph_store is not None:
        for w in await workflow_registry(rt).rows():
            if w.get("team_id") != team_id or w["status"] == "deleted" or w["published_version"] is None:
                continue
            v = await rt.graph_store.version(w["id"], int(w["published_version"]))
            for node in list(dict((v or {}).get("definition") or {}).get("nodes") or []):
                tool = str(dict(node.get("config") or {}).get("tool") or "")
                if node.get("kind") == "tool" and tool in wanted:
                    add(tool, {"kind": "workflow", "id": str(w["id"]), "name": str(w["name"])})
    # A v2 workflow (the runner's) calls a tool from a tool node; its newest version counts, draft or live, so turning
    # an app off warns about a workflow before its next publish breaks, not after.
    for d in await team_workflows(rt):
        if d.get("archived_at"):
            continue
        for node in cast(list[dict[str, Any]], dict(d.get("definition") or {}).get("nodes") or []):
            tool = str(dict(node.get("parameters") or {}).get("operation") or "")
            if node.get("type") == "ops.action.tool" and tool in wanted:
                add(tool, {"kind": "workflow", "id": str(d["workflow_id"]), "name": str(d["name"])})
    return out


@router.get("", response_model=Envelope[dict[str, list[ToolUser]]])
async def list_tool_uses(
    rt: Rt, caller: CurrentTenantCaller, tools: Annotated[str, Query(min_length=1, max_length=8000)]
) -> JSONResponse:
    """`tools` is a comma-separated list of tool names (operation names); each comes back with its users."""
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="which agents and workflows use a tool")
    names = [n for n in dict.fromkeys(t.strip() for t in tools.split(",")) if n][:MAX_TOOLS]
    return ok(await tool_uses(rt, caller.team_id, names))
