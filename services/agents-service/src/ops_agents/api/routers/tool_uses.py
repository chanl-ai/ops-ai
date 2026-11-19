"""Which of a team's agents and workflows use each tool, for a plugin update's review: a person with
agents.view in their team, or a service holding `agents:view` for the team its token names.

An agent uses a tool its newest or published version grants (`toolIds`, operation names). A workflow uses it when it
runs such an agent (the agent's "used in", `used_in_all`, v1 and v2 alike) or a published v1 workflow's tool step names
it, or a v2 workflow's tool node does. Only the team's own agents and workflows are read: no team sees another's.

Every route here reads only this service's rows, so each answers in the request transaction (`Tx`): one connection, and
one moment for the agents, workflows and versions it joins."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentTenantCaller
from ops_identity.fastapi import Tx
from ops_service_kit import narrow
from ops_service_kit.http import Envelope, Out

from ...store.pin_users import PinUsers
from ..account_names import account_uses_in
from ..child_runs import team_workflows
from ..deps import Runtime, runtime
from ..envelope import ok
from ..workflow_registry import registry as workflow_registry
from .agents import used_in_all

router = APIRouter(prefix="/v1/tool-uses")
# Which of a team's workflows read each document type, for documents-service's delete of one.
document_type_router = APIRouter(prefix="/v1/document-type-uses")
account_router = APIRouter(prefix="/v1/account-uses")
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
    holders: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    # The team's agents' newest and published versions in one query, by agent then version: the newest name wins.
    for v in await PinUsers(rt.db).held_versions(team_id):
        granted = v.spec.get("toolIds")
        held = {str(t) for t in granted} & wanted if isinstance(granted, list) else set[str]()
        names[v.agent_id] = str(v.spec.get("name") or names.get(v.agent_id) or v.slug)
        if held:
            holders.setdefault(v.agent_id, set()).update(held)
    for agent_id, held in sorted(holders.items()):
        for t in sorted(held):
            add(t, {"kind": "agent", "id": agent_id, "name": names[agent_id]})
    if holders:
        runs = await used_in_all(rt)
        for agent_id, held in holders.items():
            for use in runs.get(agent_id, []):
                if not use.get("own"):
                    for t in sorted(held):
                        add(t, {"kind": "workflow", "id": str(use["workflowId"]), "name": str(use["workflowName"])})
    if rt.graph_store is not None:
        for w in await workflow_registry(rt).rows():
            if w.team_id != team_id or w.status == "deleted" or w.published_version is None:
                continue
            v = await rt.graph_store.version(w.id, w.published_version)
            for item in narrow.entries((v.definition if v else {}).get("nodes")):
                node = narrow.an_object(item, "workflow node")
                tool = str(narrow.an_object(node.get("config") or {}, "node config").get("tool") or "")
                if node.get("kind") == "tool" and tool in wanted:
                    add(tool, {"kind": "workflow", "id": w.id, "name": w.name})
    # A v2 workflow (the runner's) calls a tool from a tool node; its newest version counts, draft or live, so turning
    # an app off warns about a workflow before its next publish breaks, not after.
    for d in await team_workflows(rt):
        if d.get("archived_at"):
            continue
        for node in cast(list[dict[str, Any]], dict(d.get("definition") or {}).get("nodes") or []):
            tool = str(dict(node.get("parameters") or {}).get("operation") or "")
            if node.get("type") == "ops.action.tool" and tool in wanted:
                add(tool, {"kind": "workflow", "id": str(d["workflow_id"]), "name": str(d["name"])})
    # Agents then workflows, each by id: the registry reads are unordered, so an updated row would otherwise move.
    return {t: sorted(uses, key=lambda u: (u["kind"], u["id"])) for t, uses in out.items()}


@router.get("", response_model=Envelope[dict[str, list[ToolUser]]])
async def list_tool_uses(
    rt: Rt, caller: CurrentTenantCaller, _: Tx, tools: Annotated[str, Query(min_length=1, max_length=8000)]
) -> JSONResponse:
    """`tools` is a comma-separated list of tool names (operation names); each comes back with its users."""
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="which agents and workflows use a tool")
    names = [n for n in dict.fromkeys(t.strip() for t in tools.split(",")) if n][:MAX_TOOLS]
    return ok(await tool_uses(rt, caller.team_id, names))


async def document_type_uses(rt: Runtime, types: list[str]) -> dict[str, list[dict[str, str]]]:
    """For each document type id, the acting team's workflows whose newest version, draft or live, has a step that
    reads it (`parameters.documentType.id`), each `{kind, id, name}` once."""
    out: dict[str, list[dict[str, str]]] = {t: [] for t in types}
    for d in await team_workflows(rt):
        if d.get("archived_at"):
            continue
        for node in cast(list[dict[str, Any]], dict(d.get("definition") or {}).get("nodes") or []):
            ref = dict(node.get("parameters") or {}).get("documentType")
            type_id = str(cast(dict[str, Any], ref).get("id") or "") if isinstance(ref, dict) else ""
            use = {"kind": "workflow", "id": str(d["workflow_id"]), "name": str(d["name"])}
            if type_id in out and use not in out[type_id]:
                out[type_id].append(use)
    return out


@document_type_router.get("", response_model=Envelope[dict[str, list[ToolUser]]])
async def list_document_type_uses(
    rt: Rt, caller: CurrentTenantCaller, _: Tx, types: Annotated[str, Query(min_length=1, max_length=8000)]
) -> JSONResponse:
    """`types` is a comma-separated list of document type ids; each comes back with the workflows that read it. A
    person with workflows.view in their team, or a service holding `workflows:view` for the team its token names."""
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "workflows", "view", team=team, what="which workflows read a document type")
    names = [n for n in dict.fromkeys(t.strip() for t in types.split(",")) if n][:MAX_TOOLS]
    return ok(await document_type_uses(rt, names))


class AccountUsers(Out):
    """The definitions that name one account of an app: what blocks its delete and warns before its rename."""

    drafts: int
    published: int
    workflows: list[str]
    agents: list[str]


@account_router.get("", response_model=Envelope[AccountUsers])
async def list_account_uses(
    rt: Rt,
    caller: CurrentTenantCaller,
    _: Tx,
    app: Annotated[str, Query(min_length=1, max_length=120)],
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> JSONResponse:
    """The acting team's workflow drafts and published versions, and agents, naming the account `name` of `app`;
    tools-service asks before it deletes an account."""
    team = None if caller.kind == "service" else caller.team_id
    can(caller, "agents", "view", team=team, what="who names an account")
    found = await account_uses_in(rt, str(caller.team_id), app, name)
    return ok(AccountUsers(**found).model_dump(by_alias=True))
