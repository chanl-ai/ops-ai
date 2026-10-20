"""`/v1/tool-modules`: the console's tool-modules contract (apps/console/src/lib/api/tool-modules-http.ts), one route
per `ToolModulesApi` method, each documented with its response model in openapi.json."""

# No `from __future__ import annotations`: the routes' `caller` dependency is a local of modules_router, and FastAPI
# resolves string annotations against module globals, where it does not exist.

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute

from ops_identity import CurrentService
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Envelope, error_responses, ok

from ..callers import caller_in
from .directory import Directory
from .schemas import (
    ApprovalRequestIn,
    BlankModuleIn,
    BulkResult,
    ConnectionIn,
    DecisionIn,
    DiscoveryResult,
    ExecutionList,
    HttpOperationIn,
    IdsIn,
    ImportOperationsIn,
    ModuleActivity,
    ModuleApproval,
    ModuleDetailsPatchIn,
    ModuleIn,
    ModuleList,
    ModuleSourceIn,
    ModuleTestIn,
    ModuleTestResult,
    NoteIn,
    OperationPatchIn,
    ReviewDecisionIn,
    RevokeIn,
    ToolCallRow,
    ToolGrantList,
    ToolModuleDetail,
)
from .service import Caller, ModuleService

ERRORS = error_responses({501: "Not available on this service yet", 502: "The source could not be reached"})


def _operation_id(route: APIRoute) -> str:
    return f"{route.tags[0]}_{route.name}".replace("-", "_") if route.tags else route.name


def executions_router(service: ModuleService, directory: Directory) -> APIRouter:
    """`GET /v1/executions`: the gateway's call log with caller identity, as the console's ToolCallRow."""

    caller = caller_in(directory)

    r = APIRouter(
        prefix="/v1/executions", tags=["executions"], responses=ERRORS, generate_unique_id_function=_operation_id
    )

    @r.get("", response_model=Envelope[ExecutionList])
    async def list_executions(  # pyright: ignore[reportUnusedFunction]
        *,
        who: Annotated[Caller, Depends(caller)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 50,
        tool: str | None = None,
        module_id: Annotated[str | None, Query(alias="moduleId")] = None,
        thread: str | None = None,
        decision: Annotated[str | None, Query(pattern="^(allow|deny)$")] = None,
        key: Annotated[str | None, Query(max_length=200)] = None,
    ) -> JSONResponse:
        data = await service.executions(
            who,
            page=page,
            page_size=page_size,
            tool=tool,
            module_id=module_id,
            thread_id=thread,
            decision=decision,
            key=key,
        )
        return ok(data)

    @r.get("/{call_id}", response_model=Envelope[ToolCallRow])
    async def get_execution(call_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One call by its id, as the list shows it, so an Activity row opens to its call (c-057 T013)."""
        return ok(await service.execution(who, call_id))

    return r


def modules_router(service: ModuleService, directory: Directory) -> APIRouter:
    """The registry's routes; the caller comes from ops_identity (`callers.caller_in`)."""

    caller = caller_in(directory)

    r = APIRouter(
        prefix="/v1/tool-modules", tags=["tool-modules"], responses=ERRORS, generate_unique_id_function=_operation_id
    )

    @r.get("", response_model=Envelope[ModuleList])
    async def list_modules(  # pyright: ignore[reportUnusedFunction]
        *,
        who: Annotated[Caller, Depends(caller)],
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=200)] = 25,
        view: Annotated[str, Query(pattern="^(all|needs_approval|expiring|expired|failing|security_review)$")] = "all",
        search: str | None = None,
        sort_by: Annotated[str | None, Query(alias="sortBy")] = None,
        sort_order: Annotated[str | None, Query(alias="sortOrder", pattern="^(asc|desc)$")] = None,
        type: Annotated[list[str] | None, Query()] = None,
        access: Annotated[list[str] | None, Query()] = None,
        approval_state: Annotated[list[str] | None, Query(alias="approvalState")] = None,
        template_id: Annotated[str | None, Query(alias="templateId")] = None,
    ) -> JSONResponse:
        filters = {"type": type or [], "access": access or [], "approvalState": approval_state or []}
        # The provisioner finds the module that fills a template slot by it (c-180).
        filters["templateId"] = [template_id] if template_id else []
        data = await service.list(
            who,
            page=page,
            page_size=page_size,
            view=view,
            search=search,
            filters=filters,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return ok(data)

    @r.post("/discover", response_model=Envelope[DiscoveryResult])
    async def discover(  # pyright: ignore[reportUnusedFunction]
        body: ModuleSourceIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.discover(who, body.model_dump()))

    @r.post("/blank", response_model=Envelope[ToolModuleDetail], status_code=201)
    async def create_blank_module(body: BlankModuleIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.create_blank(who, body.model_dump()), 201)

    @r.post("/bulk-delete", response_model=Envelope[BulkResult])
    async def bulk_remove_modules(body: IdsIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.bulk_remove(who, body.ids))

    @r.post("", response_model=Envelope[ToolModuleDetail], status_code=201)
    async def create_module(body: ModuleIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.create(who, body.model_dump()), 201)

    # Before /{module_id}, which would otherwise read "grants" as a module id.
    @r.get("/grants", response_model=Envelope[ToolGrantList])
    async def list_grants(  # pyright: ignore[reportUnusedFunction]
        *,
        who: Annotated[Caller, Depends(caller)],
        view: Annotated[str, Query(pattern="^(active|expiring|requested|expired|ended|all)$")] = "all",
        search: str | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 25,
    ) -> JSONResponse:
        """Every workflow's access to the modules the team sees (c-144): a page of one view, with each view's count."""
        return ok(await service.grants(who, view=view, search=search, page=page, page_size=page_size))

    @r.get("/{module_id}", response_model=Envelope[ToolModuleDetail])
    async def get_module(module_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get(who, module_id))

    @r.patch("/{module_id}", response_model=Envelope[ToolModuleDetail])
    async def update_module_details(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ModuleDetailsPatchIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.update_details(who, module_id, body.model_dump()))

    @r.delete("/{module_id}", status_code=204, response_class=Response)
    async def remove_module(module_id: str, who: Annotated[Caller, Depends(caller)]) -> Response:  # pyright: ignore[reportUnusedFunction]
        await service.remove(who, module_id)
        return Response(status_code=204)

    @r.post("/{module_id}/operations", response_model=Envelope[ToolModuleDetail])
    async def add_operation(
        module_id: str, body: HttpOperationIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.add_operation(who, module_id, body.model_dump()))

    @r.post("/{module_id}/operations/import", response_model=Envelope[ToolModuleDetail])
    async def import_operations(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ImportOperationsIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.import_operations(who, module_id, body.model_dump()))

    @r.patch("/{module_id}/operations/{operation_id}", response_model=Envelope[ToolModuleDetail])
    async def update_operation(  # pyright: ignore[reportUnusedFunction]
        module_id: str, operation_id: str, body: OperationPatchIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        patch = body.model_dump()
        if body.binding is not None:
            # Stored as the console sends it (bindTo), like the seeded bindings.
            patch["binding"] = body.binding.model_dump(by_alias=True)
        return ok(await service.update_operation(who, module_id, operation_id, patch, body.model_fields_set))

    @r.put("/{module_id}/connection", response_model=Envelope[ToolModuleDetail])
    async def set_connection(
        module_id: str, body: ConnectionIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.set_connection(who, module_id, body.connection_id))

    @r.post("/{module_id}/versions", response_model=Envelope[ToolModuleDetail])
    async def publish_version(module_id: str, body: NoteIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.publish(who, module_id, body.note))

    @r.delete("/{module_id}/pending-changes", response_model=Envelope[ToolModuleDetail])
    async def discard_changes(module_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.discard(who, module_id))

    @r.post("/{module_id}/reviews", response_model=Envelope[ToolModuleDetail])
    async def request_review(module_id: str, body: NoteIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.request_review(who, module_id, body.note))

    @r.post("/{module_id}/review-decisions", response_model=Envelope[ToolModuleDetail])
    async def apply_review_decision(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ReviewDecisionIn, svc: CurrentService
    ) -> JSONResponse:
        """A decision made in agents-service's Reviews (c-163). Only agents-service sends it, with its own token: a
        person decides in Reviews, never here."""
        if svc.sub != "service:agents":
            raise Forbidden("Only agents-service applies a review decision.", code="service_required")
        return ok(
            await service.apply_decision(
                svc.tenant_id,
                module_id,
                request_id=body.request_id,
                version=body.version,
                decision=body.decision,
                reason=body.reason,
                by=body.by,
            )
        )

    @r.post("/{module_id}/approvals", response_model=Envelope[ModuleApproval], status_code=201)
    async def request_approval(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ApprovalRequestIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.request_approval(who, module_id, body.model_dump()), 201)

    @r.post("/{module_id}/approvals/revoke", response_model=Envelope[BulkResult])
    async def revoke_approvals(module_id: str, body: RevokeIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.revoke_approvals(who, module_id, body.ids, body.reason))

    @r.post("/{module_id}/approvals/{approval_id}/decide", response_model=Envelope[ModuleApproval])
    async def decide_approval(  # pyright: ignore[reportUnusedFunction]
        module_id: str, approval_id: str, body: DecisionIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        return ok(await service.decide_approval(who, module_id, approval_id, body.decision, body.reason))

    @r.post("/{module_id}/test", response_model=Envelope[ModuleTestResult])
    async def test_operation(
        module_id: str, body: ModuleTestIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        # Unset keys stay out, so a draft that leaves the mock or transform out uses the operation's own.
        return ok(await service.test(who, module_id, body.model_dump(exclude_unset=True)))

    @r.get("/{module_id}/activity", response_model=Envelope[ModuleActivity])
    async def module_activity(module_id: str, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.activity(who, module_id))

    return r
