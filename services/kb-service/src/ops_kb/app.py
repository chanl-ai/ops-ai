"""kb-service's FastAPI app: department knowledge bases, their file sources, and passages cited by page and section
(c-056; the surface is in docs/services/kb-service/overview.md, at the paths apps/console's knowledge-http.ts
calls)."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import Auth, CurrentCaller, CurrentTenantCaller, ServiceClient, install_auth
from ops_service_kit.http import (
    Envelope,
    ListResult,
    OptionsPage,
    Out,
    error_responses,
    install_error_handlers,
    ok,
    operation_id,
)
from ops_service_kit.settings import Settings
from ops_store.team_scope import acting_team_of, set_acting_team

from .agents import AgentDirectory, AgentsUsage
from .files import FileIntake, file_intake
from .schemas import (
    AddedDocuments,
    AddedFile,
    AttachIn,
    ChangeList,
    DocumentRow,
    FileIdsIn,
    Item,
    ItemWithDetail,
    KnowledgeBase,
    KnowledgeBaseDetail,
    KnowledgeBaseIn,
    KnowledgeBasePatch,
    KnowledgeBaseRow,
    KnowledgeChange,
    Lookups,
    NamedRef,
    OwnerIn,
    PageIn,
    PlaygroundAnswer,
    QueryIn,
    SearchIn,
    SearchOut,
    Source,
    SourceDetail,
    SourceIn,
    SourcePatch,
    SourceRow,
    SyncIn,
    SyncRun,
    VerifyIn,
)
from .service import KnowledgeService, Who
from .store import AsyncEngine, KnowledgeStore, reachable
from .store.fulltext import PostgresFullTextRetriever


class Health(Out):
    status: str
    reason: str | None = None


async def who(p: CurrentCaller) -> Who:
    """The caller; what it may change is `can()`'s, from its verified roles (c-149). The provisioning service may call
    with a token scoped to one team (c-180); like any service it needs `knowledge:view` even to read."""
    if p.kind == "service":
        can(p, "knowledge", "view", what="knowledge")
    # A person, key or dev caller reads as the team it acts in (c-407); a service reads the tenant's, as
    # knowledge_reader says.
    set_acting_team(acting_team_of(p, services=False))
    return Who(tenant_id=p.tenant_id, email=p.email or p.sub, team_id=p.team_id, caller=p)


Caller = Annotated[Who, Depends(who)]


async def knowledge_reader(p: CurrentTenantCaller) -> Who:
    """Knowledge-base refs and search (c-168, c-222): a person with knowledge.view in their team reads their team's
    bases and those no team owns; a service holding `knowledge:view` reads the tenant's, by the ids it already checked
    against its agent's grants, so no team is needed (a workflow worker acts with none)."""
    if p.kind == "service":
        can(p, "knowledge", "view", what="knowledge")
    else:
        can(p, "knowledge", "view", team=p.team_id, what="knowledge")
    set_acting_team(acting_team_of(p, services=False))
    return Who(tenant_id=p.tenant_id, email=p.email or p.sub, team_id=p.team_id, caller=p)


KnowledgeReader = Annotated[Who, Depends(knowledge_reader)]
Page = Annotated[int, Query(ge=1)]
PageSize = Annotated[int, Query(alias="pageSize", ge=1, le=100)]


def _agents_service(settings: Settings) -> AgentsUsage:
    http = httpx.AsyncClient(base_url=settings.agents_url or f"http://127.0.0.1:{settings.port}", timeout=5)
    return AgentsUsage(
        ServiceClient.for_settings(settings, http, service="kb", audience="agents", scopes=["agents:view"], timeout=5)
    )


def create_kb_app(
    engine: AsyncEngine,
    *,
    auth: Auth | None = None,
    files: FileIntake | None = None,
    agents: AgentDirectory | None = None,
) -> FastAPI:
    """`auth` resolves callers through ops_identity's shared dependency; by default built from Settings for audience
    "kb". An admin administers the knowledge bases and sources of the teams it is admin of, and no others (there is
    no tenant-wide role yet). `files` stores uploads; by default files-service when Settings().files_url names it,
    else under kb_files_dir. `agents` says which agents cite each base; by default agents-service at
    Settings().agents_url."""
    app = FastAPI(title="kb-service", version="0.1.0", generate_unique_id_function=operation_id)
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(Settings(), audience="kb"))
    # The console calls this service from its own origin, so the browser preflights every request; without this
    # every knowledge page fails before the first byte, with no server-side error to see.
    cors_origins = Settings().cors_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id"],
            max_age=600,
        )
    service = KnowledgeService(
        KnowledgeStore(engine),
        files or file_intake(Settings()),
        PostgresFullTextRetriever(engine),
        agents or _agents_service(Settings()),
    )
    errors = error_responses()

    @app.get(
        "/health",
        tags=["health"],
        response_model=Health,
        response_model_exclude_none=True,
        responses={503: {"model": Health}},
    )
    async def health() -> dict[str, str] | JSONResponse:  # pyright: ignore[reportUnusedFunction]
        if not await reachable(engine):
            return JSONResponse({"status": "degraded", "reason": "database"}, status_code=503)
        return {"status": "ok"}

    kbs = APIRouter(prefix="/v1/knowledge-bases", tags=["knowledge-bases"], responses=errors)

    @kbs.get("", response_model=Envelope[ListResult[KnowledgeBaseRow]])
    async def list_knowledge_bases(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        page: Page = 1,
        page_size: PageSize = 25,
        search: str | None = None,
        template_id: Annotated[str | None, Query(alias="templateId")] = None,
    ) -> JSONResponse:
        return ok(await service.list_bases(who, page=page, page_size=page_size, search=search, template_id=template_id))

    @kbs.get("/options", response_model=Envelope[OptionsPage])
    async def knowledge_base_options(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        search: str = "",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        ids: Annotated[list[str] | None, Query()] = None,
    ) -> JSONResponse:
        """Knowledge bases a picker offers, searched and limited in the query: the caller's team's and those no team
        owns. `ids` labels stored values instead of searching."""
        return ok(await service.base_options(who, search=search, cursor=cursor, limit=limit, ids=ids))

    @kbs.get("/refs", response_model=Envelope[list[NamedRef]])
    async def knowledge_base_refs(caller: KnowledgeReader) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Knowledge bases by id and name, for agents-service's grant check and thread names, and for a person's picker
        or script: the tenant's for a service, the team's and unowned ones for a person."""
        return ok([{"id": b["id"], "name": b["name"]} for b in await service.readable_bases(caller)])

    @kbs.post("/search", response_model=Envelope[SearchOut])
    async def search_knowledge(body: SearchIn, caller: KnowledgeReader) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Passages for an agent's turn (agents-service sends only the bases the agent is granted) or for a person, who
        searches only bases they may read."""
        limit = max(1, min(body.limit, 20))
        passages = await service.search(caller, body.kb_ids, body.question, limit=limit)
        return ok({"passages": passages})

    @kbs.get("/{kb_id}", response_model=Envelope[KnowledgeBaseDetail])
    async def get_knowledge_base(kb_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get_base(who, kb_id))

    @kbs.post("", status_code=201, response_model=Envelope[KnowledgeBase])
    async def create_knowledge_base(body: KnowledgeBaseIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.create_base(who, body.model_dump(by_alias=True)), 201)

    @kbs.patch("/{kb_id}", response_model=Envelope[KnowledgeBase])
    async def update_knowledge_base(kb_id: str, body: KnowledgeBasePatch, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.update_base(who, kb_id, body.model_dump(exclude_none=True)))

    @kbs.post("/{kb_id}/sources", response_model=Envelope[KnowledgeBase])
    async def attach_sources(kb_id: str, body: AttachIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.attach(who, kb_id, body.source_ids))

    @kbs.get("/{kb_id}/documents", response_model=Envelope[ListResult[DocumentRow]])
    async def list_documents(  # pyright: ignore[reportUnusedFunction]
        kb_id: str, who: Caller, page: Page = 1, page_size: PageSize = 25, search: str | None = None
    ) -> JSONResponse:
        return ok(await service.documents(who, kb_id, page=page, page_size=page_size, search=search))

    @kbs.post("/{kb_id}/pages", status_code=201, response_model=Envelope[Item])
    async def add_page(kb_id: str, body: PageIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.add_page(who, kb_id, body.title, body.text), 201)

    @kbs.post("/{kb_id}/documents", response_model=Envelope[AddedDocuments])
    async def add_documents(kb_id: str, body: FileIdsIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Files already in Files, added to the base's documents source (made the first time) and synced at once."""
        return ok(await service.add_documents(who, kb_id, body.file_ids))

    @kbs.post("/{kb_id}/query", response_model=Envelope[PlaygroundAnswer])
    async def query_knowledge_base(kb_id: str, body: QueryIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.query(who, kb_id, body.question))

    @kbs.delete("/{kb_id}/sources/{source_id}", response_model=Envelope[KnowledgeBase])
    async def detach_source(kb_id: str, source_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.detach(who, kb_id, source_id))

    @kbs.post("/{kb_id}/refresh", response_model=Envelope[KnowledgeBase])
    async def refresh_knowledge_base(kb_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.refresh(who, kb_id))

    @kbs.post("/{kb_id}/retry-failed", response_model=Envelope[KnowledgeBase])
    async def retry_failed(kb_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.refresh(who, kb_id, retry=True))

    @kbs.delete("/{kb_id}", status_code=204, response_class=Response)
    async def remove_knowledge_base(kb_id: str, who: Caller) -> Response:  # pyright: ignore[reportUnusedFunction]
        await service.remove_base(who, kb_id)
        return Response(status_code=204)

    sources = APIRouter(prefix="/v1/sources", tags=["sources"], responses=errors)

    @sources.get("", response_model=Envelope[ListResult[SourceRow]])
    async def list_sources(  # pyright: ignore[reportUnusedFunction]
        who: Caller, page: Page = 1, page_size: PageSize = 25, search: str | None = None
    ) -> JSONResponse:
        return ok(await service.list_sources(who, page=page, page_size=page_size, search=search))

    @sources.get("/{source_id}", response_model=Envelope[SourceDetail])
    async def get_source(source_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get_source(who, source_id))

    @sources.post("", status_code=201, response_model=Envelope[Source])
    async def create_source(body: SourceIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.create_source(who, body.model_dump(by_alias=True)), 201)

    @sources.post("/{source_id}/files", response_model=Envelope[list[AddedFile]])
    async def add_files(source_id: str, body: FileIdsIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Files already in Files, by id: each must be the team's and scanned clean, and is referenced there so it is
        kept while the source reads it. The next sync indexes them."""
        return ok(await service.add_files(who, source_id, body.file_ids))

    @sources.post("/{source_id}/sync", response_model=Envelope[SyncRun])
    async def sync_source(source_id: str, who: Caller, body: SyncIn | None = None) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        opts = body or SyncIn()
        return ok(await service.sync(who, source_id, full=opts.full, retry=opts.retry))

    @sources.get("/{source_id}/runs", response_model=Envelope[ListResult[SyncRun]])
    async def list_runs(  # pyright: ignore[reportUnusedFunction]
        source_id: str, who: Caller, page: Page = 1, page_size: PageSize = 25
    ) -> JSONResponse:
        return ok(await service.source_runs(who, source_id, page=page, page_size=page_size))

    @sources.patch("/{source_id}", response_model=Envelope[Source])
    async def update_source(source_id: str, body: SourcePatch, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.update_source(who, source_id, body.model_dump(exclude_none=True)))

    @sources.post("/{source_id}/pause", response_model=Envelope[Source])
    async def pause_source(source_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.set_paused(who, source_id, paused=True))

    @sources.post("/{source_id}/resume", response_model=Envelope[Source])
    async def resume_source(source_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.set_paused(who, source_id, paused=False))

    @sources.get("/{source_id}/items", response_model=Envelope[ListResult[Item]])
    async def list_items(  # pyright: ignore[reportUnusedFunction]
        source_id: str, who: Caller, page: Page = 1, page_size: PageSize = 25, search: str | None = None
    ) -> JSONResponse:
        return ok(await service.source_items(who, source_id, page=page, page_size=page_size, search=search))

    @sources.delete("/{source_id}", status_code=204, response_class=Response)
    async def remove_source(source_id: str, who: Caller) -> Response:  # pyright: ignore[reportUnusedFunction]
        await service.remove_source(who, source_id)
        return Response(status_code=204)

    items = APIRouter(prefix="/v1/items", tags=["items"], responses=errors)

    @items.post("/{item_id}/verify", response_model=Envelope[Item])
    async def verify_item(item_id: str, body: VerifyIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.verify_item(who, item_id, verified=body.verified))

    @items.put("/{item_id}/owner", response_model=Envelope[Item])
    async def set_item_owner(item_id: str, body: OwnerIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.set_item_owner(who, item_id, body.owner))

    @items.get("/{item_id}", response_model=Envelope[ItemWithDetail])
    async def get_item(item_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.item(who, item_id))

    changes = APIRouter(prefix="/v1/knowledge-changes", tags=["changes"], responses=errors)

    @changes.get("", response_model=Envelope[ChangeList])
    async def list_changes(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        *,
        page: Page = 1,
        page_size: PageSize = 25,
        search: str | None = None,
        view: str = "resolved",
        kb_id: Annotated[str | None, Query(alias="kbId")] = None,
    ) -> JSONResponse:
        return ok(
            await service.list_changes(who, view=view, kb_id=kb_id, page=page, page_size=page_size, search=search)
        )

    @changes.get("/{change_id}", response_model=Envelope[KnowledgeChange])
    async def get_change(change_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get_change(who, change_id))

    runs = APIRouter(prefix="/v1/sync-runs", tags=["sources"], responses=errors)

    @runs.get("/{run_id}", response_model=Envelope[SyncRun])
    async def get_run(run_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get_run(who, run_id))

    @app.get("/v1/knowledge/lookups", tags=["knowledge-bases"], response_model=Envelope[Lookups], responses=errors)
    async def lookups(who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.lookups(who))

    app.include_router(runs)
    app.include_router(changes)
    app.include_router(kbs)
    app.include_router(items)
    app.include_router(sources)
    return app
