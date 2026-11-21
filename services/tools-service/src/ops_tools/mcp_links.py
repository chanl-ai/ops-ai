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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field, JsonValue

from ops_access import Access, can
from ops_identity import Principal
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound, Unprocessable
from ops_service_kit.http import Envelope, In, ListResult, Out, ok
from ops_service_kit.listing import ListQuery
from ops_service_kit.names import Name, Name120

from .callers import caller_in
from .mcp_server import WORKFLOW_PREFIX
from .modules.directory import Directory
from .modules.routes import ERRORS
from .modules.service import Caller
from .registry import ToolRegistry
from .store.mcp_links import LinkedTool, McpLinkRow, McpLinks

# A link names its tools; past this many an assistant reads a list too long to choose from (tool search starts at 20).
MAX_TOOLS = 20
WORKFLOW_ID = "workflow:"
ACCESS = Access()


class PickedTool(In):
    # A tool as the tools picker names it: an operation's name, or `workflow:<id>` for a published workflow.
    id: str = Field(min_length=1, max_length=200)
    label: Name
    # For a workflow, what the link picker's option said it takes and does (agents-service's catalog), listed to
    # assistants in tools/list. It only describes: agents-service checks the input again when the run starts.
    input_schema: dict[str, JsonValue] | None = None
    description: str | None = Field(default=None, max_length=2000)


class McpLinkIn(In):
    name: Name120
    environment: Literal["test"] = "test"
    tools: list[PickedTool] = Field(min_length=1, max_length=MAX_TOOLS)


class McpLinkPatch(In):
    paused: bool


class LinkTool(Out):
    name: str
    title: str
    kind: Literal["tool", "workflow"]
    access: Literal["read", "write", "workflow"]


class LastCall(Out):
    at: str
    outcome: str
    client: str | None
    signed_in: bool


class McpLinkView(Out):
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
    links: McpLinks, registry: ToolRegistry, directory: Directory, public_url: str | None
) -> APIRouter:
    caller = caller_in(directory)
    base = public_url.rstrip("/") if public_url else None
    r = APIRouter(prefix="/v1/mcp-links", tags=["mcp-links"], responses=ERRORS)

    def _principal(who: Caller) -> Principal:
        # caller_in names every route's caller from its token, so a principal is always there.
        assert who.principal is not None
        return who.principal

    def _view(row: McpLinkRow) -> McpLinkView:
        tools = [LinkTool(name=t.name, title=t.title, kind=t.kind, access=t.access) for t in row.tools]
        return McpLinkView(
            id=row.id,
            name=row.name,
            slug=row.slug,
            team_id=row.team_id,
            environment="test",
            url=f"{base}/mcp/{row.team_id}/{row.slug}" if base else None,
            tools=tools,
            tool_count=len(tools),
            paused=row.paused,
            created_by=row.created_by,
            created_at=row.created_at,
            last_call=LastCall(
                # A signed-in assistant is known by its client id only; the console words it rather than show the id.
                at=row.last_at,
                outcome=row.last_outcome or "",
                client=row.last_client_name,
                signed_in=row.last_client_id is not None,
            )
            if row.last_at is not None
            else None,
        )

    async def _one(who: Caller, link_id: str) -> McpLinkRow:
        row = await links.one(who.tenant_id, who.team.id, link_id)
        if row is None:
            raise NotFound(f"MCP link {link_id}")
        return row

    @r.get("", response_model=Envelope[ListResult[McpLinkView]])
    async def list_mcp_links(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)],
        _: Tx,
        q: ListQuery,
        team_id: Annotated[list[str] | None, Query(alias="teamId", description="the links' team")] = None,
    ) -> JSONResponse:
        """The links of every team the caller may see channels in, by name ignoring case, a page at a time on the
        shared list contract (`search` on the name), each with its newest call; `teamId` (repeatable) keeps those
        teams' links and is counted in `facets`. A person reads the team they act in; the dev caller and a service
        token every team they may see, and a `teamId` outside those answers no rows."""
        # Read from `q.filters`; declared so the document and the SDKs name it.
        del team_id
        p = _principal(who)
        can(p, "deployments", "view", team=who.team.id, what="this team's MCP links")
        teams = [t for t in dict.fromkeys([who.team.id, *p.team_ids]) if ACCESS.may(p, "deployments", "view", team=t)]
        page = await links.listed(who.tenant_id, teams, q)
        views = [_view(McpLinkRow.model_validate(x)).model_dump(by_alias=True) for x in page["data"]]
        return ok({**page, "data": views})

    @r.post("", response_model=Envelope[McpLinkView], status_code=201)
    async def create_mcp_link(body: McpLinkIn, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Makes a link in the acting team. Each picked operation must be one the team may run now; a picked workflow
        is checked when it is started, as agents-service decides who may start it. 422 when the name's address is
        taken in the team."""
        p = _principal(who)
        can(p, "deployments", "create", team=who.team.id, what="an MCP link")
        team = who.team

        def sees(m: Any, operation: str | None = None) -> bool:
            return directory.sees_module(team, m, operation)

        grantable = {str(x["name"]): x for x in await registry.grantable(who.tenant_id, sees)}
        picked: list[LinkedTool] = []
        for t in body.tools:
            if t.id.startswith(WORKFLOW_ID):
                wid = t.id.removeprefix(WORKFLOW_ID)
                picked.append(
                    LinkedTool(
                        name=f"{WORKFLOW_PREFIX}{wid}",
                        title=t.label,
                        kind="workflow",
                        access="workflow",
                        description=t.description,
                        input_schema=t.input_schema or {"type": "object"},
                    )
                )
            elif (op := grantable.get(t.id)) is not None:
                access = "write" if op["access"] not in ("read",) else "read"
                picked.append(LinkedTool(name=t.id, title=t.label, kind="tool", access=access))
            else:
                raise Unprocessable(f"{t.label} is not a tool this team can run.", code="tool_not_runnable")
        row = await links.create(
            who.tenant_id, team.id, slug=slug_of(body.name), name=body.name.strip(), tools=picked, by=who.name
        )
        made = McpLinkRow(
            **row.model_dump(), last_at=None, last_outcome=None, last_client_name=None, last_client_id=None
        )
        return ok(_view(made).model_dump(by_alias=True), status=201)

    @r.get("/{link_id}", response_model=Envelope[McpLinkView])
    async def get_mcp_link(link_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        can(_principal(who), "deployments", "view", team=who.team.id, what="this team's MCP links")
        return ok(_view(await _one(who, link_id)).model_dump(by_alias=True))

    @r.patch("/{link_id}", response_model=Envelope[McpLinkView])
    async def pause_mcp_link(  # pyright: ignore[reportUnusedFunction]
        link_id: str, body: McpLinkPatch, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:
        """Pauses or resumes the link: while paused its address refuses every request with the reason."""
        can(_principal(who), "deployments", "edit", team=who.team.id, what="this MCP link")
        if not await links.set_paused(who.tenant_id, who.team.id, link_id, body.paused):
            raise NotFound(f"MCP link {link_id}")
        return ok(_view(await _one(who, link_id)).model_dump(by_alias=True))

    @r.delete("/{link_id}", status_code=204)
    async def delete_mcp_link(link_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Deletes the link: its address answers 404 and no key made for it opens anything. Its calls stay listed in
        Activity."""
        can(_principal(who), "deployments", "delete", team=who.team.id, what="this MCP link")
        if not await links.delete(who.tenant_id, who.team.id, link_id):
            raise NotFound(f"MCP link {link_id}")
        return Response(status_code=204)

    return r
