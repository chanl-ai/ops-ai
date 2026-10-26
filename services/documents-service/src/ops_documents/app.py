# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's HTTP API (c-256): extractions and their corrections under /v1/documents, document types,
versions, samples and test runs under /v1/document-types, and the purge a file-deleted workflow calls. The shapes are
the ones files-service served (c-235, c-236), so a caller changes only its base URL.

People act in the team their sign-in selected, checked with `can()` on the `documents` area; services act in the team
their token names and need the matching `documents:<action>` scope."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ops_access import can
from ops_documents.document_types import DocumentTypes
from ops_documents.errors import (
    CreateNotAllowedError,
    DocumentsError,
    DocumentTypeMissingError,
    FileMissingError,
    FileNotReadyError,
    IdempotencyConflictError,
    InvalidRequestError,
    StateError,
)
from ops_documents.extraction import Extractor
from ops_documents.files import Who
from ops_documents.layouts import Layouts, page_of
from ops_documents.models import (
    Classification,
    ClassifyIn,
    CorrectionIn,
    DocumentType,
    DocumentTypeExample,
    DocumentTypeIn,
    DocumentTypeList,
    DocumentTypeVersion,
    DocumentTypeVersionIn,
    Extraction,
    ExtractionRequest,
    Layout,
    LayoutIn,
    Purged,
    PurgeIn,
    Sample,
    SampleIn,
    TemplateOffer,
    TemplateSuggestIn,
    TemplateSuggestion,
    TestEstimate,
    TestRun,
)
from ops_documents.store import DocumentTypesStore, ExtractionsStore, LayoutsStore, NameTakenError
from ops_documents.store.metadata import reachable
from ops_identity import Auth, CurrentCaller, Principal, install_auth
from ops_service_kit.background import BackgroundHealthOut
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, ValidationFailed
from ops_service_kit.http import (
    Envelope,
    ListResult,
    error_body,
    error_responses,
    install_error_handlers,
    ok,
    operation_id,
    paged,
)
from ops_service_kit.settings import Settings
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import report as background_report


class Health(BaseModel):
    status: str
    reason: str | None = None


def _status(e: DocumentsError) -> ApiError:
    message = str(e) or type(e).__name__
    if isinstance(e, DocumentTypeMissingError):
        return NotFound("Document type")
    if isinstance(e, FileMissingError):
        return NotFound("File")
    if isinstance(e, CreateNotAllowedError):
        return Forbidden(message, code="role_required")
    if isinstance(e, FileNotReadyError | StateError | IdempotencyConflictError):
        return Conflict(message)
    if isinstance(e, InvalidRequestError):
        return ValidationFailed(message)
    return ApiError(message)


def service_scope(action: str, *, services_only: bool = False) -> Any:
    """Opens a route to services holding `documents:<action>`; `services_only` refuses people."""

    def mark(request: Request) -> None:
        request.state.documents_action = action
        request.state.documents_services_only = services_only

    return Depends(mark)


async def who(p: CurrentCaller, request: Request) -> Who:
    action: str | None = getattr(request.state, "documents_action", None)
    if p.kind == "service":
        if action is None:
            raise Forbidden("This route does not take service tokens.", code="scope_required")
        if not p.tenant_id:
            raise Forbidden("The service token names no tenant.", code="tenant_required")
        if f"documents:{action}" not in p.scopes:
            raise Forbidden(f"This service token does not hold the documents:{action} scope.", code="scope_required")
        if not p.team_id:
            raise Forbidden("A service token for a team's documents names that team.", code="team_required")
        can(p, "documents", action, team=p.team_id, what="documents")
        return Who(tenant_id=p.tenant_id, team=p.team_id, actor=p.sub)
    if getattr(request.state, "documents_services_only", False):
        raise Forbidden("Only a service does this.", code="scope_required")
    if not p.team_id:
        raise Forbidden("Choose a team to work with documents in.", code="team_required")
    if action is not None:
        can(
            p,
            "documents",
            "view" if action == "view" else "run" if action == "run" else "view",
            team=p.team_id,
            what="documents",
        )
    return Who(
        tenant_id=p.tenant_id,
        team=p.team_id,
        actor=p.email or p.sub,
        edits=_holds(p, "edit"),
        manages=_holds(p, "manage"),
    )


def _holds(p: Principal, action: str) -> bool:
    try:
        can(p, "documents", action, team=p.team_id, what="documents")
    except Forbidden:
        return False
    return True


Caller = Annotated[Who, Depends(who)]
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", description="A retry with the same key reads the same extraction.")
]


def create_documents_app(
    *,
    engine: Any,
    extractor: Extractor,
    document_types: DocumentTypes,
    auth: Auth | None = None,
    layouts: Layouts | None = None,
    background: Sequence[Callable[[], Coroutine[Any, Any, None]]] = (),
) -> FastAPI:
    """`extractor` and `document_types` read bytes through files-service as the caller's team; `auth` resolves
    callers through ops_identity, by default from Settings for audience "documents". `layouts` serves the layout
    routes, by default the extractor's own, else a cache on `engine`."""
    config = Settings()
    layouts = layouts or extractor.layouts or Layouts(extractor.files, LayoutsStore(engine))

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Extractions and test runs queued or running when the process stopped run again.
        await extractor.resume()
        await document_types.resume()
        # Work that runs beside the server, such as the service event relay, stopped with it.
        tasks = [asyncio.create_task(start()) for start in background]
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    app = FastAPI(
        title="documents-service", version="0.1.0", lifespan=lifespan, generate_unique_id_function=operation_id
    )
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(config, audience="documents"))
    if config.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(config.cors_origins),
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id", "Idempotency-Key"],
            max_age=600,
        )

    @app.exception_handler(DocumentsError)
    async def documents_error(request: Request, e: DocumentsError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        api = _status(e)
        return JSONResponse(error_body(api.status, api.code, api.message), status_code=api.status)

    errors = error_responses({409: "Not ready or already in another state"})

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

    @app.get("/health/background", tags=["health"], response_model=BackgroundHealthOut)
    async def health_background() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
        """This service's background processes and their state; counts and error types only, no record's data."""
        return {"processes": background_report(await LOCAL_BEATS.read(), "documents", time.time())}

    def found(value: Any, what: str) -> Any:
        if value is None:
            raise NotFound(what)
        return value

    docs = APIRouter(prefix="/v1/documents", tags=["documents"], responses=errors)

    @docs.post(
        "/extractions",
        response_model=Envelope[Extraction],
        responses={
            202: {"model": Envelope[Extraction], "description": "Queued; poll GET /v1/documents/extractions/{id}"}
        },
        dependencies=[service_scope("run")],
    )
    async def extract(body: ExtractionRequest, who: Caller, idempotency_key: IdempotencyKey = None) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A file's fields by the schema or a document type, each with value, confidence, page, quote and
        needsReview against the field's, the schema's and the workspace floor. Up to 5 pages and 5 MB the answer comes
        at once; a larger file answers 202 with the extraction's id to poll."""
        request = body.model_dump(mode="json", by_alias=True, exclude={"file_id"})
        status, answer = await extractor.ask(who, body.file_id, request, idempotency_key=idempotency_key)
        return ok(answer, status)

    @docs.get("/extractions", response_model=Envelope[ListResult[Extraction]], dependencies=[service_scope("view")])
    async def file_extractions(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        file_id: str = Query(alias="fileId", min_length=1, max_length=64),
        page: int = Query(1, ge=1),
        page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    ) -> JSONResponse:
        """A file's extractions by the caller's team, newest first; a file the team cannot see is 404."""
        rows, total = await extractor.for_file(who, file_id, page=page, page_size=page_size)
        return ok(paged(rows, total, page, page_size))

    @docs.post("/classifications", response_model=Envelope[Classification], dependencies=[service_scope("run")])
    async def classify_file(body: ClassifyIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Which of the team's document types the file is, by the model over each type's name and description
        (c-249); typeId null and needsReview when none fits or the model is less sure than the floor."""
        file = await extractor.files.readable(who, body.file_id)
        return ok(await extractor.classify(who, file, ocr=body.ocr))

    @docs.post("/layout", response_model=Envelope[Layout], dependencies=[service_scope("run")])
    async def compute_layout(body: LayoutIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The file's layout: pages, blocks in reading order with table cells, and words with confidence, boxes as
        fractions of the page. Read on the first ask and cached by the file's content digest (c-247)."""
        return ok(await layouts.compute(who, body.file_id, ocr=body.ocr))

    @docs.get("/layout/{file_id}", response_model=Envelope[Layout], dependencies=[service_scope("view")])
    async def get_layout(  # pyright: ignore[reportUnusedFunction]
        file_id: str,
        who: Caller,
        page: int | None = Query(None, ge=1),
        ocr: bool = False,
    ) -> JSONResponse:
        """The layout already read for the file, or one page of it; 404 until POST /v1/documents/layout reads it."""
        found = await layouts.cached(who, file_id, ocr=ocr)
        if found is None:
            raise NotFound("Layout")
        return ok(page_of(found, page) if page is not None else found)

    @docs.get("/extractions/{extraction_id}", response_model=Envelope[Extraction], dependencies=[service_scope("view")])
    async def get_extraction(extraction_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(found(await extractor.get(who, extraction_id), "Extraction"))

    @docs.patch(
        "/extractions/{extraction_id}/fields/{key}",
        response_model=Envelope[Extraction],
        dependencies=[service_scope("edit")],
    )
    async def correct_field(extraction_id: str, key: str, body: CorrectionIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A checker's value for one field; the original value and confidence are kept beside it."""
        if not who.edits:
            raise CreateNotAllowedError("Your role in this team cannot correct documents.")
        return ok(found(await extractor.correct(who, extraction_id, key, body.value, record=body.record), "Extraction"))

    @docs.post("/purge", response_model=Envelope[Purged], dependencies=[service_scope("delete", services_only=True)])
    async def purge(body: PurgeIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Removes what the token's team derived from a deleted file: its extractions with their corrections, and the
        samples naming it. A workflow on the file-deleted trigger calls this; files-service never does. A file
        files-service still serves the team is refused (409), so a purge can never remove the reads of a live file."""
        try:
            await extractor.files.readable(who, body.file_id)
        except FileMissingError:
            pass
        except FileNotReadyError:
            raise StateError(f"{body.file_id} still exists; only a deleted file is purged") from None
        else:
            raise StateError(f"{body.file_id} still exists; only a deleted file is purged")
        removed = await extractor.store.purge(who.team, body.file_id)
        samples = await document_types.store.purge_samples(who.team, body.file_id)
        return ok({"extractions": removed, "samples": samples})

    types = APIRouter(prefix="/v1/document-types", tags=["document-types"], responses=errors)

    @types.post("", status_code=201, response_model=Envelope[DocumentType], dependencies=[service_scope("edit")])
    async def create_type(body: DocumentTypeIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A document type and its version 1; the name is unique in the team."""
        try:
            made = await document_types.create(who, body.model_dump(mode="json", by_alias=True))
        except NameTakenError as e:
            raise Conflict(f"A document type named {body.name} or with id {body.id} exists.", code="name_taken") from e
        return ok(made, 201)

    @types.get("", response_model=Envelope[DocumentTypeList], dependencies=[service_scope("view")])
    async def list_types(who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The team's types, and whether the caller may add one (the console's New type)."""
        return ok({"items": await document_types.list(who), "canCreate": who.edits})

    @types.get("/{type_id}", response_model=Envelope[DocumentType], dependencies=[service_scope("view")])
    async def get_type(type_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(found(await document_types.get(who, type_id), "Document type"))

    @types.post(
        "/{type_id}/versions",
        status_code=201,
        response_model=Envelope[DocumentTypeVersion],
        dependencies=[service_scope("edit")],
    )
    async def add_version(type_id: str, body: DocumentTypeVersionIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The type's next version; earlier versions stay as they were."""
        made = await document_types.add_version(who, type_id, body.model_dump(mode="json", by_alias=True))
        return ok(found(made, "Document type"), 201)

    @types.get(
        "/{type_id}/versions/{version}",
        response_model=Envelope[DocumentTypeVersion],
        dependencies=[service_scope("view")],
    )
    async def get_version(type_id: str, version: int, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(found(await document_types.get_version(who, type_id, version), "Document type version"))

    @types.post(
        "/{type_id}/templates/suggest",
        response_model=Envelope[TemplateSuggestion],
        dependencies=[service_scope("edit")],
    )
    async def suggest_template(type_id: str, body: TemplateSuggestIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A layout template drafted from the team's finished reads of the type, and how it reads each; nothing is
        saved until a builder posts it as a new version (c-254)."""
        return ok(found(await document_types.suggest_template(who, type_id, body.extraction_ids), "Document type"))

    @types.get(
        "/{type_id}/template-offers",
        response_model=Envelope[list[TemplateOffer]],
        dependencies=[service_scope("view")],
    )
    async def template_offers(type_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Groups of at least 5 checked model reads of one layout that no current template reads (c-254)."""
        return ok(found(await document_types.template_offers(who, type_id), "Document type"))

    @types.get(
        "/{type_id}/examples",
        response_model=Envelope[list[DocumentTypeExample]],
        dependencies=[service_scope("view")],
    )
    async def list_examples(type_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The corrections people made on the type's reads, which its later reads are given, newest first (c-297)."""
        return ok(found(await document_types.list_examples(who, type_id), "Document type"))

    @types.delete(
        "/{type_id}/examples/{example_id}",
        status_code=204,
        response_class=Response,
        dependencies=[service_scope("edit")],
    )
    async def remove_example(type_id: str, example_id: str, who: Caller) -> Response:  # pyright: ignore[reportUnusedFunction]
        """Later reads of the type are no longer given this example."""
        if not await document_types.remove_example(who, type_id, example_id):
            raise NotFound("Example")
        return Response(status_code=204)

    @types.post(
        "/{type_id}/samples", status_code=201, response_model=Envelope[Sample], dependencies=[service_scope("edit")]
    )
    async def add_sample(type_id: str, body: SampleIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A team file and the values it should read; Files keeps the file while the sample names it."""
        made = await document_types.add_sample(who, type_id, body.model_dump(mode="json", by_alias=True))
        return ok(found(made, "Document type"), 201)

    @types.delete(
        "/{type_id}/samples/{sample_id}", status_code=204, response_class=Response, dependencies=[service_scope("edit")]
    )
    async def remove_sample(type_id: str, sample_id: str, who: Caller) -> Response:  # pyright: ignore[reportUnusedFunction]
        if not await document_types.remove_sample(who, type_id, sample_id):
            raise NotFound("Sample")
        return Response(status_code=204)

    @types.get(
        "/{type_id}/versions/{version}/test-estimate",
        response_model=Envelope[TestEstimate],
        dependencies=[service_scope("view")],
    )
    async def test_estimate(type_id: str, version: int, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """What testing the version spends: calls and cost, before it runs."""
        return ok(found(await document_types.estimate(who, type_id, version), "Document type version"))

    @types.post(
        "/{type_id}/versions/{version}/test-runs",
        status_code=202,
        response_model=Envelope[TestRun],
        dependencies=[service_scope("edit")],
    )
    async def run_test(type_id: str, version: int, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Runs every sample (at most 20) through extraction with this version; poll the test for its results."""
        return ok(found(await document_types.start_test(who, type_id, version), "Document type version"), 202)

    @types.get("/{type_id}/test-runs/{test_id}", response_model=Envelope[TestRun], dependencies=[service_scope("view")])
    async def get_test(type_id: str, test_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok(found(await document_types.get_test(who, type_id, test_id), "Test run"))

    app.include_router(docs)
    app.include_router(types)
    return app


def build_stores(engine: Any) -> tuple[ExtractionsStore, DocumentTypesStore]:
    return ExtractionsStore(engine), DocumentTypesStore(engine)
