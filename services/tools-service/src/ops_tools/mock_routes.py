"""`/v1/tool-modules/{id}/operations/{op}/mocks`: an operation's mock answers in test. Every member of the
module's team reads them; changing them is `tools.edit` (a system module's, `tools.manage` too). They never reach
production, so they are not module versions and need no Security review."""

# No `from __future__ import annotations`: FastAPI resolves the `Depends(caller)` annotations at import, and
# `caller` is local to the router factory.
from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, Response
from pydantic import Field

from ops_access import Access, reader_of
from ops_identity.fastapi import Tx
from ops_service_kit.errors import NotFound, ValidationFailed
from ops_service_kit.http import Envelope, In, Json, JsonValue, ListResult, Out, ok
from ops_service_kit.ids import new_id
from ops_service_kit.listing import ListQuery

from .callers import caller_in
from .mocks import MAX_WAIT_MS
from .modules.directory import Directory, owns_module
from .modules.routes import ERRORS
from .modules.service import Caller
from .store.mocks import MOCK_CHANGE, MOCK_ROW, MockRow, MockStore, NewMock
from .store.modules import Module, ModuleStore, Operation

# What a mock's body may weigh, as an operation's stub may (modules/service.py MAX_STUB_BYTES).
MAX_BODY_CHARS = 64_000


class MockIn(In):
    name: str = Field(min_length=1, max_length=200)
    # test: answers test-environment calls; example: the operation's example answer, one per operation.
    environment: Literal["test", "example"] = "test"
    # Input field to the value it must equal; empty matches every call (use it as the default).
    match: dict[str, JsonValue] = Field(default_factory=dict[str, JsonValue])
    status: int = Field(default=200, ge=100, le=599)
    body: JsonValue = None
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    delay_ms: int = Field(default=0, ge=0, le=MAX_WAIT_MS)
    timeout: bool = False
    default: bool = False


class MockPatchIn(In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    match: dict[str, JsonValue] | None = None
    status: int | None = Field(default=None, ge=100, le=599)
    body: JsonValue = None
    headers: dict[str, str] | None = None
    delay_ms: int | None = Field(default=None, ge=0, le=MAX_WAIT_MS)
    timeout: bool | None = None
    default: bool | None = None


class MockAnswer(Out):
    id: str
    name: str
    environment: str
    position: int
    match: dict[str, JsonValue]
    status: int
    body: JsonValue = None
    headers: dict[str, str]
    delay_ms: int
    timeout: bool
    default: bool
    from_call_id: str | None = None
    created_by: str
    updated_at: str


class MockList(ListResult[MockAnswer]):
    """One page of an operation's mocks, with the operation's name."""

    operation: str


def _view(row: MockRow) -> Json:
    return MockAnswer(
        id=row["id"],
        name=row["name"],
        environment=row["environment"],
        position=row["position"],
        match=row["match"] or {},
        status=row["status"],
        body=row.get("body"),
        headers=row["headers"] or {},
        delay_ms=row["delay_ms"],
        timeout=row["timeout"],
        default=row["is_default"],
        from_call_id=row.get("from_call_id"),
        created_by=row["created_by"],
        updated_at=row["updated_at"].isoformat(),
    ).model_dump(by_alias=True)


def mocks_router(mocks: MockStore, modules: ModuleStore, directory: Directory) -> APIRouter:
    caller = caller_in(directory)
    r = APIRouter(prefix="/v1/tool-modules", tags=["tool-modules"], responses=ERRORS)

    async def _operation(who: Caller, module_id: str, op_id: str) -> tuple[Module, Operation]:
        """The module, seen from the caller's team (404 otherwise, as every module read), and its operation."""
        m = await modules.get(who.tenant_id, module_id)
        if m is None or not (directory.sees_module(who.team, m) or (not who.verified and who.team.scope == "all")):
            raise NotFound(f"Module {module_id}")
        op = next((o for o in m["operations"] if o["id"] == op_id), None)
        if op is None:
            raise NotFound(f"Operation {op_id}")
        return m, op

    def _may_edit(who: Caller, m: Module) -> None:
        # A team that reads the module through a workflow's grant changes none of its answers: 404, as an unseen one.
        if not owns_module(who.team, m.get("team_id"), verified=who.verified):
            raise NotFound(f"Module {m['id']}")
        if who.principal is not None:
            Access().can(who.principal, "tools", "edit", what="tools", protection=m.get("protection"))

    def _checked(i: Json, op: Operation) -> None:
        names = {f["name"] for f in op["input"]}
        unknown = sorted(str(k) for k in cast(Json, i.get("match") or {}) if k not in names)
        if unknown:
            raise ValidationFailed(
                f"{', '.join(unknown)} is not an input of {op['name']}.", details={"fields": unknown}
            )
        if i.get("body") is not None and len(str(i["body"])) > MAX_BODY_CHARS:
            raise ValidationFailed(f"A mock's body is at most {MAX_BODY_CHARS} characters.")

    @r.get(
        "/{module_id}/operations/{op_id}/mocks",
        response_model=Envelope[MockList],
        dependencies=[Depends(reader_of("tools"))],
    )
    async def list_mocks(  # pyright: ignore[reportUnusedFunction]
        module_id: str,
        op_id: str,
        who: Annotated[Caller, Depends(caller)],
        _: Tx,
        q: ListQuery,
        environment: Annotated[Literal["test", "example"], Query()] = "test",
    ) -> JSONResponse:
        """The operation's mock answers in the order a test call checks them, a page at a time on the shared list
        contract (`search` on the name), or (`environment=example`) its example answer."""
        m, op = await _operation(who, module_id, op_id)
        page = await mocks.page(who.tenant_id, str(m["id"]), str(op["name"]), environment, q)
        return ok({**page, "operation": op["name"], "data": [_view(MOCK_ROW.validate_python(x)) for x in page["data"]]})

    @r.post("/{module_id}/operations/{op_id}/mocks", response_model=Envelope[MockAnswer], status_code=201)
    async def add_mock(  # pyright: ignore[reportUnusedFunction]
        module_id: str, op_id: str, body: MockIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:
        """A mock answer after the operation's others. Keeping a Try it answer is this call with that answer's status
        and body, which the test console returned already scrubbed and masked."""
        m, op = await _operation(who, module_id, op_id)
        _may_edit(who, m)
        i = body.model_dump()
        _checked(i, op)
        now = datetime.now(UTC)
        row: NewMock = {
            "tenant_id": who.tenant_id,
            "id": new_id("mck"),
            "module_id": m["id"],
            "operation": op["name"],
            "environment": i["environment"],
            "name": i["name"],
            "match": i["match"],
            "status": i["status"],
            "body": i["body"],
            "headers": i["headers"],
            "delay_ms": i["delay_ms"],
            "timeout": i["timeout"],
            "is_default": i["default"],
            "from_call_id": None,
            "created_by": who.name,
            "created_at": now,
            "updated_at": now,
        }
        await mocks.add(row)
        made = await mocks.get(who.tenant_id, str(row["id"]))
        assert made is not None
        return ok(_view(made), 201)

    @r.patch("/{module_id}/operations/{op_id}/mocks/{mock_id}", response_model=Envelope[MockAnswer])
    async def change_mock(  # pyright: ignore[reportUnusedFunction]
        module_id: str, op_id: str, mock_id: str, body: MockPatchIn, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> JSONResponse:
        m, op = await _operation(who, module_id, op_id)
        _may_edit(who, m)
        found = await mocks.get(who.tenant_id, mock_id)
        if found is None or (found["module_id"], found["operation"]) != (m["id"], op["name"]):
            raise NotFound(f"Mock {mock_id}")
        given = body.model_dump(exclude_unset=True)
        _checked(given, op)
        values = MOCK_CHANGE.validate_python({("is_default" if k == "default" else k): v for k, v in given.items()})
        changed = await mocks.change(who.tenant_id, mock_id, values, at=datetime.now(UTC))
        assert changed is not None
        return ok(_view(changed))

    @r.delete("/{module_id}/operations/{op_id}/mocks/{mock_id}", status_code=204, response_class=Response)
    async def delete_mock(  # pyright: ignore[reportUnusedFunction]
        module_id: str, op_id: str, mock_id: str, who: Annotated[Caller, Depends(caller)], _: Tx
    ) -> Response:
        m, op = await _operation(who, module_id, op_id)
        _may_edit(who, m)
        found = await mocks.get(who.tenant_id, mock_id)
        if (
            found is None
            or (found["module_id"], found["operation"]) != (m["id"], op["name"])
            or not await mocks.delete(who.tenant_id, mock_id)
        ):
            raise NotFound(f"Mock {mock_id}")
        return Response(status_code=204)

    return r
