"""`/v1/tool-modules`: the console's tool-modules contract (apps/console/src/lib/api/tool-modules-http.ts), one route
per `ToolModulesApi` method, each documented with its response model in openapi.json."""

# No `from __future__ import annotations`: the routes' `caller` dependency is a local of modules_router, and FastAPI
# resolves string annotations against module globals, where it does not exist.

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response

from ops_access import reader_of
from ops_identity import CurrentService
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Forbidden
from ops_service_kit.http import Envelope, error_responses, ok
from ops_service_kit.listing import ListQuery

from ..callers import caller_in
from ..held_hosts import HELD
from .directory import Directory
from .schemas import (
    ApprovalRequestIn,
    BlankModuleIn,
    BulkResult,
    CodeOperationIn,
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
    ToolRunIn,
    ToolRunResult,
)
from .service import Caller, ModuleService, TestRun, test_run

ERRORS = error_responses({501: "Not available on this service yet", 502: "The source could not be reached"})


def executions_router(service: ModuleService, directory: Directory) -> APIRouter:
    """`GET /v1/executions`: the gateway's call log with caller identity, as the console's ToolCallRow."""

    caller = caller_in(directory)

    r = APIRouter(prefix="/v1/executions", tags=["executions"], responses=ERRORS)

    @r.get("", response_model=Envelope[ExecutionList])
    async def list_executions(  # pyright: ignore[reportUnusedFunction]
        *,
        who: Annotated[Caller, Depends(caller)],
        q: ListQuery,
        tool: str | None = None,
        # Repeatable: an app with several tool sets lists the calls of all of them in one page.
        module_ids: Annotated[list[str] | None, Query(alias="moduleId", max_length=50)] = None,
        thread: str | None = None,
        decision: Annotated[str | None, Query(pattern="^(allow|deny)$")] = None,
        key: Annotated[str | None, Query(max_length=200)] = None,
        call: Annotated[str | None, Query(max_length=200)] = None,
        # The calls made through one MCP link (mcp_links.id).
        link: Annotated[str | None, Query(max_length=64)] = None,
        # A date range, ISO times compared as the log stores them: from `since`, before `until`.
        since: Annotated[str | None, Query(max_length=40)] = None,
        until: Annotated[str | None, Query(max_length=40)] = None,
        result: Annotated[
            list[Literal["Ran", "Running", "Refused", "Failed"]] | None,
            Query(description="Keeps the calls with these results; counted in `facets.result`"),
        ] = None,
        assistant: Annotated[
            list[str] | None,
            Query(description="Keeps the calls made by these assistants; counted in `facets.assistant`"),
        ] = None,
    ) -> JSONResponse:
        """The log on the shared list contract: `search` matches the tool's name, `result` and `assistant` narrow and
        are counted in `facets`, and the order is newest first, then by id. Off the request transaction: the
        service reads in one and asks agents-service to name the agents and workflows after it."""
        del result, assistant
        data = await service.executions(
            who,
            q,
            tool=tool,
            module_ids=module_ids,
            thread_id=thread,
            decision=decision,
            key=key,
            call_id=call,
            link_id=link,
            since=since,
            until=until,
        )
        return ok(data)

    @r.get("/{call_id}", response_model=Envelope[ToolCallRow])
    async def get_execution(call_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """One call by its id, as the list shows it, so an Activity row opens to its call."""
        return ok(await service.execution(who, call_id))

    return r


def modules_router(service: ModuleService, directory: Directory) -> APIRouter:
    """The registry's routes; the caller comes from ops_identity (`callers.caller_in`)."""

    caller = caller_in(directory)

    r = APIRouter(prefix="/v1/tool-modules", tags=["tool-modules"], responses=ERRORS)

    @r.get("", response_model=Envelope[ModuleList], dependencies=[Depends(reader_of("tools"))])
    async def list_modules(  # pyright: ignore[reportUnusedFunction]
        *,
        who: Annotated[Caller, Depends(caller)],
        _: Tx,
        q: ListQuery,
        view: Annotated[
            str, Query(description="all, needs_approval, expiring, expired, failing or security_review")
        ] = "all",
        type: Annotated[list[str] | None, Query(description="http, code or mcp")] = None,
        access: Annotated[list[str] | None, Query(description="read or write")] = None,
        approval_state: Annotated[list[str] | None, Query(alias="approvalState")] = None,
        # The provisioner finds the module that fills a template slot by it.
        template_id: Annotated[list[str] | None, Query(alias="templateId")] = None,
    ) -> JSONResponse:
        """The team's modules, one page of a view. The view and the filters are read from the shared list query; they
        are named here for the document. `sortBy` is displayName, name, calls24h, errorRate, updatedAt, operationCount
        or ownerTeam."""
        del view, type, access, approval_state, template_id
        return ok(await service.list(who, q))

    @r.post("/discover", response_model=Envelope[DiscoveryResult])
    async def discover(  # pyright: ignore[reportUnusedFunction]
        body: ModuleSourceIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Off the request transaction: it fetches the source, so no connection is held while it answers."""
        return ok(await service.discover(who, body))

    @r.post("/blank", response_model=Envelope[ToolModuleDetail], status_code=201, responses=HELD)
    async def create_blank_module(body: BlankModuleIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: a host not yet listed is sent to Security in agents-service."""
        return ok(await service.create_blank(who, body), 201)

    @r.post("/bulk-delete", response_model=Envelope[BulkResult])
    async def bulk_remove_modules(body: IdsIn, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.bulk_remove(who, body.ids))

    @r.post("", response_model=Envelope[ToolModuleDetail], status_code=201, responses=HELD)
    async def create_module(body: ModuleIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: it may fetch the source and send a new host to Security."""
        return ok(await service.create(who, body), 201)

    # Before /{module_id}, which would otherwise read "grants" as a module id.
    @r.get("/grants", response_model=Envelope[ToolGrantList], dependencies=[Depends(reader_of("tools"))])
    async def list_grants(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Caller, Depends(caller)],
        _: Tx,
        q: ListQuery,
        view: Annotated[str, Query(description="active, expiring, requested, expired, ended or all")] = "all",
    ) -> JSONResponse:
        """Every workflow's access to the modules the team sees: a page of one view, with each view's count. `view`
        is read from the shared list query's filters; it is named here for the document."""
        del view
        return ok(await service.grants(who, q))

    @r.get("/{module_id}", response_model=Envelope[ToolModuleDetail], dependencies=[Depends(reader_of("tools"))])
    async def get_module(module_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.get(who, module_id))

    @r.patch("/{module_id}", response_model=Envelope[ToolModuleDetail])
    async def update_module_details(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ModuleDetailsPatchIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:
        return ok(await service.update_details(who, module_id, body))

    @r.delete("/{module_id}", status_code=204, response_class=Response)
    async def remove_module(module_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> Response:  # pyright: ignore[reportUnusedFunction]
        await service.remove(who, module_id)
        return Response(status_code=204)

    @r.post("/{module_id}/operations", response_model=Envelope[ToolModuleDetail], responses=HELD)
    async def add_operation(
        module_id: str, body: HttpOperationIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: a host not yet listed is sent to Security in agents-service."""
        return ok(await service.add_operation(who, module_id, body))

    @r.post("/{module_id}/functions", response_model=Envelope[ToolModuleDetail])
    async def add_function(
        module_id: str, body: CodeOperationIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Adds a Python function to a code module; it runs on runner-service when called."""
        return ok(await service.add_function(who, module_id, body))

    @r.post("/{module_id}/operations/import", response_model=Envelope[ToolModuleDetail])
    async def import_operations(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ImportOperationsIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Off the request transaction: it fetches the source again before it adds the operations."""
        return ok(await service.import_operations(who, module_id, body))

    @r.patch("/{module_id}/operations/{operation_id}", response_model=Envelope[ToolModuleDetail])
    async def update_operation(  # pyright: ignore[reportUnusedFunction]
        module_id: str, operation_id: str, body: OperationPatchIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:
        return ok(await service.update_operation(who, module_id, operation_id, body, body.model_fields_set))

    @r.put("/{module_id}/connection", response_model=Envelope[ToolModuleDetail])
    async def set_connection(
        module_id: str, body: ConnectionIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.set_connection(who, module_id, body.connection_id))

    @r.post("/{module_id}/versions", response_model=Envelope[ToolModuleDetail])
    async def publish_version(module_id: str, body: NoteIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: platform-service gives the publish-review mode and a review opens in agents-
        service."""
        return ok(await service.publish(who, module_id, body.note))

    @r.delete("/{module_id}/pending-changes", response_model=Envelope[ToolModuleDetail])
    async def discard_changes(module_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.discard(who, module_id))

    @r.post("/{module_id}/reviews", response_model=Envelope[ToolModuleDetail])
    async def request_review(module_id: str, body: NoteIn, who: Annotated[Caller, Depends(caller)]) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: the review opens in agents-service."""
        return ok(await service.request_review(who, module_id, body.note))

    @r.post("/{module_id}/review-decisions", response_model=Envelope[ToolModuleDetail])
    async def apply_review_decision(  # pyright: ignore[reportUnusedFunction]
        module_id: str, body: ReviewDecisionIn, svc: CurrentService, _: Tx
    ) -> JSONResponse:
        """A decision made in agents-service's Reviews. Only agents-service sends it, with its own token: a
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
        """Off the request transaction: the workflow is read from agents-service."""
        return ok(await service.request_approval(who, module_id, body), 201)

    @r.post("/{module_id}/approvals/revoke", response_model=Envelope[BulkResult])
    async def revoke_approvals(
        module_id: str, body: RevokeIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.revoke_approvals(who, module_id, body.ids, body.reason))

    @r.post("/{module_id}/approvals/{approval_id}/decide", response_model=Envelope[ModuleApproval])
    async def decide_approval(  # pyright: ignore[reportUnusedFunction]
        module_id: str, approval_id: str, body: DecisionIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Off the request transaction: platform-service says whether the requester may decide and which writes wait."""
        return ok(await service.decide_approval(who, module_id, approval_id, body.decision, body.reason))

    @r.post("/{module_id}/test", response_model=Envelope[ModuleTestResult])
    async def test_operation(
        module_id: str, body: ModuleTestIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Off the request transaction: a real run calls the system, and a mock waits its delay."""
        return ok(await service.test(who, module_id, test_run(body)))

    @r.post("/{module_id}/operations/{operation}/run", response_model=Envelope[ToolRunResult])
    async def run_tool(  # pyright: ignore[reportUnusedFunction]
        module_id: str, operation: str, body: ToolRunIn, who: Annotated[Caller, Depends(caller)]
    ) -> JSONResponse:
        """Off the request transaction: a Real run goes through the gateway to the system. The tool page's Run, in the
        screen's words: the test console's owner try, Mock on the stub's answer and
        Real as the gateway's call, so the two never decide differently."""
        target: Literal["stub", "sandbox"] = "stub" if body.mode == "mock" else "sandbox"
        run: TestRun = {
            "operation": operation,
            "context_id": "owner",
            "target": target,
            "input": body.input,
            "environment": body.environment,
            "confirmed": body.confirmed,
        }
        out = await service.test(who, module_id, run)
        return ok({**out, "mocked": body.mode == "mock" or out.get("mockId") is not None})

    @r.get("/{module_id}/activity", response_model=Envelope[ModuleActivity])
    async def module_activity(module_id: str, who: Annotated[Caller, Depends(caller)], _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(await service.activity(who, module_id))

    return r
