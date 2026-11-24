# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""files-service's FastAPI app: uploads, completion, metadata, downloads, delete and legal holds for people
(`/v1/files`), and, on the same routes, server writes, reads, references and scan results for services holding the
`files` scope each needs.

Design, API table and rules: docs/services/files-service/overview.md.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Coroutine, Sequence
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, FastAPI, Header, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import Field

from ops_access import Access, can
from ops_files.models import (
    BulkResult,
    CompletedUpload,
    DownloadLink,
    FileDataIn,
    FileDetail,
    FileList,
    FilePurpose,
    FileReferenceType,
    ReadRequest,
    ReadRequestIn,
    UploadLimits,
    UploadRequest,
    UploadTicket,
)
from ops_files.scanning import ScanResult
from ops_files.service import (
    DeleteNotAllowedError,
    DeleteRefusedError,
    DownloadTtlError,
    EditNotAllowedError,
    FileMissingError,
    FilesError,
    InvalidUploadError,
    NotDownloadableError,
    RetentionChangeError,
    TypeNotAllowedError,
    UploadMissingError,
    UploadStateError,
    UploadTooLargeError,
    UploadVerificationError,
)
from ops_files.settings import (
    CredentialInput,
    CredentialView,
    ProbeFailedError,
    ProbeResult,
    StorageSettings,
    StorageSettingsInput,
    StorageSettingsView,
    StorageTarget,
    StorageTargetIn,
    TargetInUseError,
    UnknownCredentialError,
)
from ops_files.store import StaleVersionError, reachable
from ops_files.tenant_files import HoldRefusedError, TenantFiles, Who
from ops_identity import Auth, CurrentCaller, CurrentPrincipal, CurrentService, install_auth
from ops_identity.fastapi import Tx
from ops_service_kit.background import BackgroundHealthOut
from ops_service_kit.errors import ApiError, Conflict, Forbidden, NotFound, Unprocessable, ValidationFailed
from ops_service_kit.http import (
    Envelope,
    In,
    OptionsPage,
    Out,
    error_responses,
    install_error_handlers,
    ok,
    operation_id,
)
from ops_service_kit.listing import ListQuery
from ops_service_kit.logging import get_logger
from ops_service_kit.names import FileName
from ops_service_kit.settings import Settings
from ops_sources import Reader
from ops_storage.base import ObjectLockedError, ObjectNotFoundError, content_disposition
from ops_store import isolation
from ops_store.background import LOCAL as LOCAL_BEATS
from ops_store.background import report as background_report

_TEAM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
log = get_logger(__name__)


class PayloadTooLarge(ApiError):
    status = 413
    code = "payload_too_large"


class UnsupportedType(ApiError):
    status = 415
    code = "unsupported_media_type"


class Locked(ApiError):
    status = 423
    code = "locked"


class Health(Out):
    status: str
    reason: str | None = None


class DownloadIn(In):
    ttl_seconds: int | None = None


# The body is optional: a link asked for with none lasts the tenant's longest.
_NO_TTL = DownloadIn()


class LegalHoldIn(In):
    ids: list[str] = Field(min_length=1, max_length=100)
    hold: bool
    reason: str


class BulkDeleteIn(In):
    ids: list[str] = Field(min_length=1, max_length=100)


class ReferenceIn(In):
    type: FileReferenceType
    ref_id: str
    name: FileName
    href: str | None = None


class ScanResultIn(In):
    file_id: str
    status: Literal["clean", "infected", "failed"]
    engine: str = Field(min_length=1, max_length=64)
    detail: str | None = Field(default=None, max_length=500)
    # Which version was scanned, by number or by the SHA-256 of its bytes; required once a file has more than one, so a
    # late verdict on an older version never clears a newer one.
    version: int | None = Field(default=None, ge=1)
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


def _status(e: FilesError | HoldRefusedError | ObjectLockedError) -> ApiError:
    """The files rules' refusals as HTTP answers (files 5 and 6)."""
    message = str(e) or type(e).__name__
    if isinstance(e, HoldRefusedError):
        return Forbidden(message)
    if isinstance(e, ObjectLockedError):
        # Storage's own retention or legal hold refused the change, behind the service's checks; never a 500.
        return Conflict(message, code="locked_in_storage")
    if isinstance(e, FileMissingError):
        return NotFound("File")
    if isinstance(e, DeleteNotAllowedError | EditNotAllowedError):
        return Forbidden(message, code="role_required")
    if isinstance(e, UploadTooLargeError):
        return PayloadTooLarge(message)
    if isinstance(e, TypeNotAllowedError):
        return UnsupportedType(message)
    if isinstance(e, NotDownloadableError):
        return Locked(message)
    if isinstance(e, (UploadVerificationError, UploadMissingError, UploadStateError, DeleteRefusedError)):
        return Conflict(message)
    if isinstance(e, RetentionChangeError):
        return Conflict(message)
    if isinstance(e, (InvalidUploadError, DownloadTtlError)):
        return ValidationFailed(message)
    return ApiError(message)


def service_scope(action: str, *, services_only: bool = False) -> Any:
    """Opens a route to services holding `files:<action>`; every other files route refuses a service token.
    `services_only` refuses people. Declared in the route's `dependencies`, which run before `who`."""

    def mark(request: Request) -> None:
        request.state.files_service_action = action
        request.state.files_services_only = services_only

    return Depends(mark)


async def who(p: CurrentCaller, request: Request) -> Who:
    """The caller. A service acts in the team and tenant its signed token names; a team in a query or body is never
    read. A person acts in the team their sign-in selected."""
    action: str | None = getattr(request.state, "files_service_action", None)
    if p.kind == "service":
        if action is None:
            raise Forbidden("This files route does not take service tokens.", code="scope_required")
        if not p.tenant_id:
            raise Forbidden("The service token names no tenant.", code="tenant_required")
        if f"files:{action}" not in p.scopes:
            # Before the team: a token without the scope learns only that, whatever team it names.
            raise Forbidden(f"This service token does not hold the files:{action} scope.", code="scope_required")
        if not p.team_id:
            raise Forbidden("A service token for a team's files names that team.", code="team_required")
        can(p, "files", action, team=p.team_id, what="a file")
        return Who(tenant_id=p.tenant_id, team=p.team_id, actor=p.sub)
    if getattr(request.state, "files_services_only", False):
        raise Forbidden("Only a service records this.", code="scope_required")
    if not p.team_id:
        raise Forbidden("Choose a team to work with files in.", code="team_required")
    # files.manage (legal holds, the storage location) is an admin's in the grid; `can()` decides it.
    try:
        can(p, "files", "manage", team=p.team_id, what="files")
        admin_teams = frozenset({p.team_id})
    except Forbidden:
        admin_teams = frozenset[str]()
    try:
        can(p, "files", "delete", team=p.team_id, what="files")
        deletes = True
    except Forbidden:
        deletes = False
    try:
        # A person records what was read from a file with files.create, the members who upload: the console writes it
        # until the extract workflow's step does (TODO), and no built-in member role holds files.edit.
        can(p, "files", "create", team=p.team_id, what="files")
        edits = True
    except Forbidden:
        edits = False
    return Who(
        tenant_id=p.tenant_id,
        team=p.team_id,
        actor=p.email or p.sub,
        admin_teams=admin_teams,
        deletes=deletes,
        edits=edits,
    )


Caller = Annotated[Who, Depends(who)]
IdempotencyKey = Annotated[
    str | None, Header(alias="Idempotency-Key", description="A retry with the same key returns the same file.")
]


def _absolute(request: Request, path: str, public: str | None) -> str:
    """A URL the caller can reach: a signed storage URL as it is, else this service's route on its public base."""
    return path if "://" in path else f"{(public or str(request.base_url)).rstrip('/')}{path}"


def create_files_app(
    files: TenantFiles,
    *,
    engine: Any,
    auth: Auth | None = None,
    settings: StorageSettings | None = None,
    background: Sequence[Callable[[], Coroutine[Any, Any, None]]] = (),
    reader: Reader | None = None,
) -> FastAPI:
    """`files` holds the storage backend and tables; `auth` resolves callers through ops_identity, by default from
    Settings for audience "files": platform tokens are verified locally against platform-service's key set.
    `settings` serves the storage settings routes; without it they are not mounted. `reader` reads the sources the
    team's apps declare, which a watched folder is checked against; without it a watch cannot be added."""

    async def kept(start: Callable[[], Coroutine[Any, Any, None]]) -> None:
        # Each process reports its own failures on /health/background; one that still escapes is logged here, so it
        # never cancels the group, which would stop the server and the other processes with it.
        try:
            await start()
        except Exception as e:
            log.warning("files_background_stopped", error=f"{type(e).__name__}: {e}"[:500])

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        # Work that runs beside the server, such as the service event relay, on one TaskGroup: leaving it cancels each
        # process and waits for it, so none outlives the server.
        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(kept(start)) for start in background]
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()

    app = FastAPI(title="files-service", version="0.1.0", lifespan=lifespan, generate_unique_id_function=operation_id)
    config = Settings()
    install_error_handlers(app)
    install_auth(app, auth or Auth.from_settings(config, audience="files"))
    cors_origins = config.cors_origins
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors_origins),
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Content-Type", "Accept", "Authorization", "X-API-Key", "X-Team-Id", "Idempotency-Key"],
            expose_headers=["Content-Disposition"],
            max_age=600,
        )

    async def refused(request: Request, e: Exception) -> Response:
        """A refusal raised below the routes, rendered by the kit's ApiError handler so it answers exactly as one a
        route raises (details, the request id, Retry-After) rather than through a second copy of the envelope."""
        assert isinstance(e, FilesError | HoldRefusedError | ObjectLockedError)
        reply = app.exception_handlers[ApiError](request, _status(e))
        return reply if isinstance(reply, Response) else await reply

    for refusal in (FilesError, HoldRefusedError, ObjectLockedError):
        app.add_exception_handler(refusal, refused)

    errors = error_responses({413: "Above the purpose's size limit", 415: "Type not allowed", 423: "Not scanned clean"})

    @app.get(
        "/health",
        tags=["health"],
        response_model=Health,
        response_model_exclude_none=True,
        responses={503: {"model": Health}},
    )
    async def health(response: Response) -> Health:  # pyright: ignore[reportUnusedFunction]
        if not await reachable(engine):
            response.status_code = 503
            return Health(status="degraded", reason="database")
        return Health(status="ok")

    @app.get("/health/background", tags=["health"], response_model=BackgroundHealthOut)
    async def health_background() -> BackgroundHealthOut:  # pyright: ignore[reportUnusedFunction]
        """This service's background processes and their state; counts and error types only, no record's data."""
        return BackgroundHealthOut.model_validate(
            {"processes": background_report(await LOCAL_BEATS.read(), "files", time.time())}
        )

    public = APIRouter(prefix="/v1/files", tags=["files"], responses=errors)

    @public.post("/uploads", status_code=201, response_model=Envelope[UploadTicket])
    async def create_upload(  # pyright: ignore[reportUnusedFunction]
        body: UploadRequest, request: Request, who: Caller, idempotency_key: IdempotencyKey = None
    ) -> JSONResponse:
        """A ticket for one upload: a signed storage URL, or this service's content route on the local backend. Not
        on Tx: the rows are read in one transaction and written in another, with none open while the URL is signed
        (tests/test_request_transactions.py)."""
        ticket = await files.create_upload(who, body, idempotency_key=idempotency_key)
        ticket = ticket.model_copy(
            update={"upload_url": _absolute(request, ticket.upload_url, config.files_public_url)}
        )
        return ok(ticket.model_dump(mode="json", by_alias=True), 201)

    @public.put("/uploads/{file_id}/content", status_code=204, response_class=Response)
    async def put_content(  # pyright: ignore[reportUnusedFunction]
        file_id: str, request: Request, who: Caller, content_type: Annotated[str, Header()] = ""
    ) -> Response:
        """The proxy upload: the bytes as the body, streamed into storage. Local backend and proxy environments."""
        mime = content_type.split(";")[0].strip()
        await files.put_content(who, file_id, request.stream(), content_type=mime)
        return Response(status_code=204)

    @public.post("/uploads/{file_id}/complete", response_model=Envelope[CompletedUpload])
    async def complete_upload(file_id: str, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Checks size, type by signature and sha256, then dedupes within the team."""
        done = await files.complete(who, file_id)
        return ok(done.model_dump(mode="json", by_alias=True))

    # Services holding files:view list their token's team's files too: the read_file tool finds a file by name.
    @public.get("", response_model=Envelope[FileList], dependencies=[service_scope("view")])
    async def list_files(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        _: Tx,
        q: ListQuery,
        *,
        uploaded_by: Annotated[Literal["me"] | None, Query(alias="uploadedBy")] = None,
        purpose: Annotated[list[FilePurpose] | None, Query()] = None,
        scan: Annotated[list[str] | None, Query()] = None,
        sensitivity: Annotated[list[str] | None, Query()] = None,
        read_as: Annotated[list[str] | None, Query(alias="readAs")] = None,
        read_path: Annotated[list[Literal["template", "model"]] | None, Query(alias="readPath")] = None,
        ref_type: Annotated[FileReferenceType | None, Query(alias="refType")] = None,
        ref_id: Annotated[str | None, Query(alias="refId")] = None,
        uploaded_after: Annotated[datetime | None, Query(alias="uploadedAfter")] = None,
        uploaded_before: Annotated[datetime | None, Query(alias="uploadedBefore")] = None,
        view: Literal["all", "quarantined", "legal_hold", "unreferenced", "expiring"] = "all",
    ) -> JSONResponse:
        """Available files of the caller's team on the shared list contract, newest first (`sortBy` name, uploadedAt,
        size, scan or purpose; equal values stay newest first); `uploadedBy=me` keeps the caller's own. Search, the
        uploaded dates, the view and the purpose, scan, sensitivity, read-as type and read path filters run in the
        query, which also answers each view's count and the facet counts; `readPath=model` keeps files no template
        matched. The filters are declared here so a bad value is refused; ListQuery reads the same keys as its
        filters."""
        del purpose, scan, sensitivity, read_as, read_path
        listed = await files.list(
            who,
            q,
            mine=uploaded_by == "me",
            ref_type=ref_type,
            ref_id=ref_id,
            uploaded_after=uploaded_after,
            uploaded_before=uploaded_before,
            view=view,
        )
        return ok(listed.model_dump(mode="json", by_alias=True))

    @public.post("/{file_id}/read-requests", status_code=202, response_model=Envelope[ReadRequest])
    async def request_read(  # pyright: ignore[reportUnusedFunction]
        file_id: str, body: ReadRequestIn, who: Caller, _: Tx, idempotency_key: IdempotencyKey = None
    ) -> JSONResponse:
        """Asks for the file to be read with a document type: the system extract workflow runs as the caller,
        started by this service's file.read_requested event, and saves what was read on the file. 202 at once; the
        request carries the run once the event is delivered. A repeat with the same Idempotency-Key returns the first
        request."""
        found = await files.request_read(who, file_id, body, key=idempotency_key)
        return ok(found.model_dump(mode="json", by_alias=True), status=202)

    @public.get("/{file_id}/read-requests/{key}", response_model=Envelope[ReadRequest])
    async def get_read_request(file_id: str, key: str, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A read request and, once its event was delivered, the run it started."""
        return ok((await files.read_request(who, file_id, key)).model_dump(mode="json", by_alias=True))

    @public.put("/{file_id}/data", response_model=Envelope[FileDetail], dependencies=[service_scope("edit")])
    async def set_file_data(file_id: str, body: FileDataIn, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Records what was read from the file: its document type and version, template or model, how many fields
        wait for a person, and the extraction. The extract workflow's step writes it; files-service calls no
        other service for it."""
        stored = await files.set_data(who, file_id, body)
        return ok(stored.model_dump(mode="json", by_alias=True))

    @public.get("/options", response_model=Envelope[OptionsPage])
    async def file_options(  # pyright: ignore[reportUnusedFunction]
        who: Caller,
        _: Tx,
        search: str = "",
        cursor: str | None = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        ids: Annotated[list[str] | None, Query()] = None,
    ) -> JSONResponse:
        """The team's files a picker offers, searched and paged in the query; one not scanned clean is disabled with
        the reason. `ids` labels stored values instead of searching."""
        return ok(
            (await files.options(who, search=search, cursor=cursor, limit=limit, ids=ids)).model_dump(
                mode="json", by_alias=True
            )
        )

    @public.get("/limits", response_model=Envelope[UploadLimits])
    async def upload_limits(who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """The purpose limits uploads are checked against; readable by everyone who can upload."""
        return ok((await files.limits(who)).model_dump(mode="json", by_alias=True))

    @public.post("/bulk-delete", response_model=Envelope[BulkResult])
    async def bulk_delete(body: BulkDeleteIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Deletes each file the rules allow; one that is referenced, held or retained is skipped with the reason."""
        return ok((await files.bulk_delete(who, body.ids)).model_dump(mode="json", by_alias=True))

    @public.post("/legal-hold", response_model=Envelope[BulkResult])
    async def set_legal_hold(body: LegalHoldIn, who: Caller) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Places or releases holds; an admin of the team only, with a reason. Sets the storage-level hold too."""
        done = await files.set_legal_hold(who, body.ids, hold=body.hold, reason=body.reason)
        return ok(done.model_dump(mode="json", by_alias=True))

    @public.get("/{file_id}", response_model=Envelope[FileDetail], dependencies=[service_scope("view")])
    async def get_file(file_id: str, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        detail = await files.get(who, file_id)
        # The console shows View only and hides Delete from these instead of guessing from the caller's role.
        flags = {
            "can_edit": False,
            "can_publish": False,
            "can_delete": who.deletes and detail.delete_blocked_by is None,
        }
        return ok(detail.model_copy(update=flags).model_dump(mode="json", by_alias=True))

    @public.post("/{file_id}/download-url", response_model=Envelope[DownloadLink])
    async def download_url(  # pyright: ignore[reportUnusedFunction]
        file_id: str, request: Request, who: Caller, body: Annotated[DownloadIn, Body()] = _NO_TTL
    ) -> JSONResponse:
        """A short-lived link; 423 until the file is scanned clean. Not on Tx: no transaction is open while the link
        is signed."""
        link = await files.download_url(who, file_id, expires_in=body.ttl_seconds)
        link = link.model_copy(update={"url": _absolute(request, link.url, config.files_public_url)})
        return ok(link.model_dump(mode="json", by_alias=True))

    @public.get("/{file_id}/content", response_class=StreamingResponse, dependencies=[service_scope("view")])
    async def get_content(  # pyright: ignore[reportUnusedFunction]
        file_id: str, who: Caller, version: Annotated[int | None, Query(ge=1)] = None
    ) -> StreamingResponse:
        """A clean file's bytes: the proxy download for people, and the read agent runs, knowledge ingest and tool
        fixtures use with a service token. `version` reads an earlier version once its own scan is clean."""
        # Not on Tx: the file's rows are read in the request's one transaction, closed before the first byte is read
        # from storage, so a slow download holds no connection (tests/test_request_transactions.py).
        async with isolation.request_transaction():
            detail, chunks = await files.open_content(who, file_id, version=version)
        return await _stream(detail, chunks)

    @public.delete("/{file_id}", status_code=204, response_class=Response)
    async def delete_file(file_id: str, who: Caller) -> Response:  # pyright: ignore[reportUnusedFunction]
        """409 while the file is referenced, held or retained."""
        await files.delete(who, file_id)
        return Response(status_code=204)

    @public.post("", status_code=201, response_model=Envelope[CompletedUpload], dependencies=[service_scope("create")])
    async def write_file(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        who: Caller,
        *,
        name: str,
        purpose: FilePurpose,
        content_type: Annotated[str, Header()],
        content_length: Annotated[int, Header(gt=0)],
        uploaded_by: Annotated[str | None, Query(alias="uploadedBy")] = None,
        idempotency_key: IdempotencyKey = None,
    ) -> JSONResponse:
        """A file written in one request, the bytes as the body, with the same checks as a browser upload (files F19).
        A service names the person it writes for in `uploadedBy`; a person is always the uploader."""
        if uploaded_by and who.actor.startswith("service:"):
            who = Who(tenant_id=who.tenant_id, team=who.team, actor=uploaded_by)
        upload = UploadRequest(name=name, size=content_length, mime=content_type.split(";")[0].strip(), purpose=purpose)
        done = await files.write(who, upload, request.stream(), idempotency_key=idempotency_key)
        return ok(done.model_dump(mode="json", by_alias=True), 201)

    @public.post("/scan-results", response_model=Envelope[FileDetail])
    async def scan_result(body: ScanResultIn, caller: CurrentService, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A scanner's verdict on one version of a file of the token's tenant; that version stays pending and unreadable
        until then, and 400 when a file of several versions is not told which. Only
        a token holding `files:decide`, which Settings.service_scopes gives the scanner alone, records one."""
        if not caller.tenant_id:
            raise Forbidden("The service token names no tenant.", code="tenant_required")
        can(caller, "files", "decide", what="a file's scan verdict")
        detail = await files.record_scan(
            caller.tenant_id,
            body.file_id,
            ScanResult(body.status, body.engine, body.detail),
            version=body.version,
            digest=body.digest,
        )
        return ok(detail.model_dump(mode="json", by_alias=True))

    @public.post(
        "/{file_id}/references",
        response_model=Envelope[FileDetail],
        dependencies=[service_scope("edit", services_only=True)],
    )
    async def attach(file_id: str, body: ReferenceIn, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """A service records that one of its records uses the file; 409 when it is pending or quarantined."""
        detail = await files.add_reference(
            who,
            file_id,
            type=body.type,
            ref_id=body.ref_id,
            name=body.name,
            href=body.href,
            owner=who.actor.removeprefix("service:"),
        )
        return ok(detail.model_dump(mode="json", by_alias=True))

    @public.delete(
        "/{file_id}/references/{ref_type}/{ref_id}",
        response_model=Envelope[FileDetail],
        dependencies=[service_scope("edit", services_only=True)],
    )
    async def detach(file_id: str, ref_type: FileReferenceType, ref_id: str, who: Caller, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        detail = await files.remove_reference(who, file_id, type=ref_type, ref_id=ref_id)
        return ok(detail.model_dump(mode="json", by_alias=True))

    app.include_router(public)
    # Imported here: the watches routes read this module's `who`, so they load once it has.
    from ops_files.store import WatchesStore  # noqa: PLC0415
    from ops_files.watch_routes import watches_router  # noqa: PLC0415

    app.include_router(watches_router(WatchesStore(engine), reader=reader), responses=errors)
    if settings is not None:
        app.include_router(_settings_router(settings))
    return app


# The rule tool secrets follow, so a `{{NAME}}` reference reads differently from a lowercase input everywhere.
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
# Names saved before that rule (2026-10-17): they keep resolving, may be replaced and deleted, and are renamed by saving
# the credential under a new name, pointing the targets at it, and deleting the old one.
_OLD_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


async def storage_admin(p: CurrentPrincipal) -> Who:
    """settings.manage, held in the workspace's Security team (Security admin in the grid): storage settings decide
    where every team's files are kept."""
    access = Access()
    access.can(p, "settings", "manage", what="storage settings", code="admin_only")
    return Who(tenant_id=p.tenant_id, team=p.team_id or access.security_team_of(p) or "", actor=p.email or p.sub)


StorageAdmin = Annotated[Who, Depends(storage_admin)]


def _settings_router(settings: StorageSettings) -> APIRouter:
    """/v1/settings/storage: where each purpose stores its bytes and the credentials it signs in with. An admin on
    the Security team only, as for egress and secrets (roles-and-permissions); storage locations are not shown to
    anyone else (files 8.1). No route returns a credential's value."""
    errors = error_responses(
        {
            403: "Not an admin on the Security team",
            409: "A stale version, or a target or credential still in use",
            422: "A target failed its test or names no credential",
        }
    )
    router = APIRouter(prefix="/v1/settings/storage", tags=["settings"], responses=errors)

    rule = "A credential name is capital letters, digits and _, starting with a letter, up to 64 (like BANK_S3)."

    async def named(tenant: str, name: str) -> str:
        """A new name follows the rule; an old-style name is accepted only for the credential that already has it."""
        if _NAME.fullmatch(name) or (_OLD_NAME.fullmatch(name) and await settings.has_credential(tenant, name)):
            return name
        raise ValidationFailed(rule)

    @router.get("", response_model=Envelope[StorageSettingsView])
    async def get_settings(who: StorageAdmin, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok((await settings.view(who.tenant_id)).model_dump(mode="json", by_alias=True))

    @router.put("", response_model=Envelope[StorageSettingsView])
    async def save_settings(body: StorageSettingsInput, who: StorageAdmin) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Saves the next version; 409 when `version` is not the saved one, 422 naming the purpose whose target fails
        its test (nothing is saved), 409 when a target that still holds files is dropped."""
        try:
            view = await settings.save(who.tenant_id, body, by=who.actor)
        except StaleVersionError as e:
            raise Conflict(str(e), code="stale_version") from e
        except ProbeFailedError as e:
            details = {"purpose": e.purpose, "steps": [s.model_dump() for s in e.result.steps]}
            raise Unprocessable(str(e), code="target_test_failed", details=details) from e
        except TargetInUseError as e:
            raise Conflict(str(e), code="target_in_use") from e
        except UnknownCredentialError as e:
            raise Unprocessable(str(e), code="unknown_credential") from e
        return ok(view.model_dump(mode="json", by_alias=True))

    @router.post("/test", response_model=Envelope[ProbeResult])
    async def test_target(body: StorageTargetIn, who: StorageAdmin) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Writes, reads and deletes a small object on the target with its credential; saves nothing."""
        target = StorageTarget.model_validate(body.model_dump())
        return ok((await settings.test(who.tenant_id, target)).model_dump(mode="json", by_alias=True))

    @router.get("/credentials", response_model=Envelope[list[CredentialView]])
    async def list_credentials(who: StorageAdmin, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return ok([c.model_dump(mode="json", by_alias=True) for c in await settings.credentials(who.tenant_id)])

    @router.put("/credentials/{name}", response_model=Envelope[CredentialView])
    async def set_credential(name: str, body: CredentialInput, who: StorageAdmin, _: Tx) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Sets or replaces a credential. The values are sealed and never returned; the answer names it only."""
        view = await settings.set_credential(who.tenant_id, await named(who.tenant_id, name), body, by=who.actor)
        return ok(view.model_dump(mode="json", by_alias=True))

    @router.delete("/credentials/{name}", status_code=204, response_class=Response)
    async def delete_credential(name: str, who: StorageAdmin, _: Tx) -> Response:  # pyright: ignore[reportUnusedFunction]
        try:
            if not (_NAME.fullmatch(name) or _OLD_NAME.fullmatch(name)):
                raise ValidationFailed(rule)
            gone = await settings.delete_credential(who.tenant_id, name, by=who.actor)
        except TargetInUseError as e:
            raise Conflict(str(e), code="credential_in_use") from e
        if not gone:
            raise NotFound(f"Storage credential {name}")
        return Response(status_code=204)

    return router


async def _stream(detail: FileDetail, chunks: AsyncIterator[bytes]) -> StreamingResponse:
    """The bytes with their length. The first chunk is read before the answer starts: a stored object that is gone
    raises only on the first read, and once the headers are out the connection can only be cut, which a browser reports
    as a length mismatch with no status."""
    try:
        first = await anext(chunks, b"")
    except ObjectNotFoundError as e:
        raise NotFound("This file's content is missing from storage.") from e

    async def body() -> AsyncIterator[bytes]:
        yield first
        async for chunk in chunks:
            yield chunk

    return StreamingResponse(
        body(),
        media_type=detail.mime,
        headers={
            "Content-Disposition": content_disposition(detail.name),
            "Content-Length": str(detail.size),
            "X-Content-Type-Options": "nosniff",
        },
    )


__all__ = ["create_files_app", "who"]
