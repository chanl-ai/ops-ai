"""`/v1/mcp-links`: the team's MCP links, each a named address for a chosen set of its tools and published workflows.

Any member of the team reads the links and how to connect (`deployments.view`); a team admin or builder makes one and
pauses or resumes it (`deployments.create`, `deployments.edit`), as for every other channel. A link is a filter on
the team's one MCP door (mcp_server.py), so it adds no second server and no second call log: its calls are the gateway's
rows with its id, listed by `GET /v1/executions?link=<id>`.
"""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import, and
# `caller` is local to the router factory.
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from ops_access import can
from ops_identity import Principal
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, ok

from .callers import caller_in
from .mcp_server import WORKFLOW_PREFIX
from .modules.directory import Directory
from .modules.routes import ERRORS
from .modules.service import Caller
from .registry import ToolRegistry
from .store.calls import CallLog
from .store.mcp_links import McpLinks

# A link names its tools; past this many an assistant reads a list too long to choose from (tool search starts at 20).
MAX_TOOLS = 20
WORKFLOW_ID = "workflow:"


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class PickedTool(_Wire):
    # A tool as the tools picker names it: an operation's name, or `workflow:<id>` for a published workflow.
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=200)


class McpLinkIn(_Wire):
    name: str = Field(min_length=1, max_length=120)
    environment: Literal["test"] = "test"
    tools: list[PickedTool] = Field(min_length=1, max_length=MAX_TOOLS)


class McpLinkPatch(_Wire):
    paused: bool


class LinkTool(_Wire):
    name: str
    title: str
    kind: Literal["tool", "workflow"]
    access: Literal["read", "write", "workflow"]


class LastCall(_Wire):
    at: str
    outcome: str
    client: str | None


class McpLinkView(_Wire):
    id: str
    name: str
    slug: str
    team_id: str
    environment: Literal["test"]
    # The address an assistant connects to; null while the install names no public address for its MCP service.
    url: str | None
    tools: list[LinkTool]
    tool_count: int
    paused: bool
    created_by: str
    created_at: str
    last_call: LastCall | None


def slug_of(name: str) -> str:
    """The address part for a link's name: lowercase words joined by hyphens, as an assistant shows it."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:64] or "link"


def mcp_links_router(
    links: McpLinks, log: CallLog, registry: ToolRegistry, directory: Directory, public_url: str | None
) -> APIRouter:
    caller = caller_in(directory)
    base = public_url.rstrip("/") if public_url else None
    r = APIRouter(prefix="/v1/mcp-links", tags=["mcp-links"], responses=ERRORS)

    def _principal(who: Caller) -> Principal:
        # caller_in names every route's caller from its token, so a principal is always there.
        assert who.principal is not None
        return who.principal

    def _view(row: dict[str, Any], last: dict[str, Any] | None) -> dict[str, Any]:
        tools = [LinkTool(name=t["name"], title=t["title"], kind=t["kind"], access=t["access"]) for t in row["tools"]]
        return McpLinkView(
            id=row["id"],
            name=row["name"],
            slug=row["slug"],
            team_id=row["team_id"],
            environment="test",
            url=f"{base}/mcp/{row['team_id']}/{row['slug']}" if base else None,
            tools=tools,
            tool_count=len(tools),
            paused=row["paused"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            last_call=LastCall(
                at=last["created_at"], outcome=last["outcome"], client=last["client_name"] or last["client_id"]
            )
            if last
            else None,
        ).model_dump(by_alias=True)

    async def _one(who: Caller, link_id: str) -> dict[str, Any]:
        row = await links.get(who.tenant_id, who.team.id, link_id)
        if row is None:
            raise NotFound(f"MCP link {link_id}")
        return row

    @r.get("", response_model=Envelope[list[McpLinkView]])
    async def list_mcp_links(who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's links by name, each with its newest call."""
        can(_principal(who), "deployments", "view", team=who.team.id, what="this team's MCP links")
        rows = await links.list(who.tenant_id, who.team.id)
        last = await log.last_by_link(who.tenant_id, who.team.id, [x["id"] for x in rows])
        return ok([_view(x, last.get(x["id"])) for x in rows])

    @r.post("", response_model=Envelope[McpLinkView], status_code=201)
    async def create_mcp_link(body: McpLinkIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Makes a link in the acting team. Each picked operation must be one the team may run now; a picked workflow
        is checked when it is started, as agents-service decides who may start it. 422 when the name's address is
        taken in the team."""
        p = _principal(who)
        can(p, "deployments", "create", team=who.team.id, what="an MCP link")
        team = who.team

        def sees(module: Any) -> bool:
            return directory.sees_module(team, module)

        grantable = {str(x["name"]): x for x in await registry.grantable(who.tenant_id, sees)}
        picked: list[dict[str, Any]] = []
        for t in body.tools:
            if t.id.startswith(WORKFLOW_ID):
                wid = t.id.removeprefix(WORKFLOW_ID)
                picked.append(
                    {"name": f"{WORKFLOW_PREFIX}{wid}", "title": t.label, "kind": "workflow", "access": "workflow"}
                )
            elif (op := grantable.get(t.id)) is not None:
                access = "write" if op["access"] not in ("read",) else "read"
                picked.append({"name": t.id, "title": t.label, "kind": "tool", "access": access})
            else:
                raise Unprocessable(f"{t.label} is not a tool this team can run.", code="tool_not_runnable")
        row = await links.create(
            who.tenant_id, team.id, slug=slug_of(body.name), name=body.name.strip(), tools=picked, by=who.name
        )
        return ok(_view(row, None), status=201)

    @r.get("/{link_id}", response_model=Envelope[McpLinkView])
    async def get_mcp_link(link_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        can(_principal(who), "deployments", "view", team=who.team.id, what="this team's MCP links")
        row = await _one(who, link_id)
        last = await log.last_by_link(who.tenant_id, who.team.id, [row["id"]])
        return ok(_view(row, last.get(row["id"])))

    @r.patch("/{link_id}", response_model=Envelope[McpLinkView])
    async def pause_mcp_link(  # pyright: ignore[reportUnusedFunction]
        link_id: str, body: McpLinkPatch, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Pauses or resumes the link: while paused its address refuses every request with the reason."""
        can(_principal(who), "deployments", "edit", team=who.team.id, what="this MCP link")
        await _one(who, link_id)
        row = await links.set_paused(who.tenant_id, who.team.id, link_id, body.paused)
        assert row is not None
        last = await log.last_by_link(who.tenant_id, who.team.id, [row["id"]])
        return ok(_view(row, last.get(row["id"])))

    return r
