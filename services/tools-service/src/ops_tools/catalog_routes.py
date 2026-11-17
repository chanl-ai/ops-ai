"""`GET /v1/tool-catalog`: the tenant's tool catalogue as the events that build it, for another service rebuilding
its copy from scratch (agents-service's `tool_catalog` and `tool_team_state`). A service token holding `tools:view`
only: a person reads tools through the module routes, which apply their team."""

# No `from __future__ import annotations`: FastAPI resolves the route's annotations at import.
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ops_access import can
from ops_identity import CurrentService
from ops_identity.fastapi import Tx
from ops_service_kit.http import Envelope, error_responses, ok

from .store.catalog import CatalogPage, ToolCatalog

# Modules per page: each brings one event and one per team granted it.
MAX_PAGE = 500


def catalog_router(store: ToolCatalog) -> APIRouter:
    r = APIRouter(prefix="/v1/tool-catalog", tags=["tool-catalog"], responses=error_responses())

    @r.get("", response_model=Envelope[CatalogPage])
    async def tool_catalog(  # pyright: ignore[reportUnusedFunction]
        svc: CurrentService,
        _: Tx,
        after: Annotated[str | None, Query(max_length=64)] = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 200,
    ) -> JSONResponse:
        """One page of the token's tenant's modules, every team's, by id past `after`; `nextCursor` is the next
        page's `after`, null on the last."""
        can(svc, "tools", "view", what="the tool catalogue")
        page = await store.page(svc.tenant_id, after=after, limit=limit)
        return ok(page.model_dump(by_alias=True, mode="json"))

    return r
