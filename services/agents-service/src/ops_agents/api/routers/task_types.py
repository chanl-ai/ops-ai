"""`/v1/task-types`: the records a Human Task screen is drawn from.

Every member of the tenant reads every type, seeded or a team's, so a workflow may use a type another team keeps.
Creating, saving and publishing one are workflow building (`workflows.create`, `workflows.edit`, `workflows.publish`)
in the owning team; a seeded type is read-only, and a team copies it to change it.

Every route answers in one request transaction (`Tx`), the seeding of the tenant's types included: they touch this
service's database only."""

from __future__ import annotations

from typing import Annotated, Any, TypeAlias

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_identity.fastapi import Tx
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Envelope, In, ListResult
from ops_service_kit.listing import ListQuery

from ... import task_types as tt
from ..auth import Principal, caller_in, caller_of
from ..deps import Runtime, runtime
from ..envelope import ok
from ..task_type_seeds import task_type_store
from ..typed_record_routes import RecordTypeView, RecordVersionView, by_of, detail, owned, store_team, team_of, view

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("workflows"))]  # noqa: UP040

router = APIRouter(prefix="/v1/task-types")


class Definition(In):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    params: dict[str, Any]
    regions: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    defaults: dict[str, Any] | None = None


class TypeRef(In):
    id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)


class TypeIn(In):
    id: str = Field(min_length=3, max_length=64)
    # Start from this type's published version (the newest when no version); the fields below replace its own.
    copy_of: TypeRef | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    params: dict[str, Any] | None = None
    regions: list[dict[str, Any]] | None = None
    actions: list[dict[str, Any]] | None = None
    defaults: dict[str, Any] | None = None


class PublishIn(In):
    version: int = Field(ge=1)


class TaskTypeView(RecordTypeView):
    pass


class TaskTypeVersionView(RecordVersionView):
    pass


class TaskTypeDetail(TaskTypeView):
    versions: list[TaskTypeVersionView]


def _checked(content: dict[str, Any]) -> dict[str, Any]:
    try:
        tt.check_definition(content)
    except tt.TypeDefinitionError as e:
        raise Unprocessable(str(e), code="invalid_task_type") from None
    return content


@router.get("", response_model=Envelope[ListResult[TaskTypeView]])
async def list_task_types(rt: Rt, me: Me, _: Tx, q: ListQuery) -> JSONResponse:
    """Every task type of the team on the shared list contract: the seeded ones first, then the team's own, each by
    name, then by id; `search` matches the name and description and `ids` names types."""
    listed, shown = await (await task_type_store(rt, store_team(me))).page(q)
    return ok({**listed, "data": [view(r) for r in shown]})


@router.get("/{type_id}", response_model=Envelope[TaskTypeDetail])
async def get_task_type(rt: Rt, me: Me, _: Tx, type_id: str) -> JSONResponse:
    """A type with each of its versions, newest first."""
    return ok(detail(await (await task_type_store(rt, store_team(me))).get(type_id)))


async def create_type(rt: Runtime, me: Principal, body: TypeIn) -> None:
    """A team's type as draft v1: from nothing, or a copy of another type's published version with edits."""
    team = team_of(me, "task type")
    can(caller_of(me), "workflows", "create", team=team, what="a task type")
    if not tt.valid_id(body.id):
        raise Unprocessable("id: lowercase letters, digits and underscores, starting with a letter.", code="invalid_id")
    store = await task_type_store(rt, store_team(me))
    base: dict[str, Any] = {}
    copied: dict[str, Any] | None = None
    if body.copy_of is not None:
        n, base = await store.published(body.copy_of.id, body.copy_of.version)
        copied = {"id": body.copy_of.id, "version": n}
    given = body.model_dump(exclude={"id", "copy_of"}, exclude_none=True)
    content = _checked({**base, **given})
    if not content.get("name"):
        raise Unprocessable("name is required.", code="invalid_task_type")
    await store.create(body.id, content, team_id=team, by=by_of(me), copied_from=copied)


@router.post("", response_model=Envelope[TaskTypeDetail], status_code=201)
async def create_task_type(rt: Rt, me: Me, _: Tx, body: TypeIn) -> JSONResponse:
    """A team's type as draft v1: from nothing, or a copy of another type's published version with edits."""
    await create_type(rt, me, body)
    return ok(detail(await (await task_type_store(rt, store_team(me))).get(body.id)), 201)


async def save_type(rt: Runtime, me: Principal, type_id: str, body: Definition) -> None:
    """Saves the draft: edits it in place, or opens the next version over a published one."""
    store = await task_type_store(rt, store_team(me))
    await owned(store, me, type_id, "edit")
    await store.save_draft(type_id, _checked(body.model_dump(exclude_none=True)), by=by_of(me))


@router.put("/{type_id}/draft", response_model=Envelope[TaskTypeDetail])
async def save_task_type(rt: Rt, me: Me, _: Tx, type_id: str, body: Definition) -> JSONResponse:
    """Saves the draft: edits it in place, or opens the next version over a published one."""
    await save_type(rt, me, type_id, body)
    return ok(detail(await (await task_type_store(rt, store_team(me))).get(type_id)))


@router.post("/{type_id}/publish", response_model=Envelope[TaskTypeDetail])
async def publish_task_type(rt: Rt, me: Me, _: Tx, type_id: str, body: PublishIn) -> JSONResponse:
    """Publishes the newest draft. Tasks already open keep the version they were opened with."""
    store = await task_type_store(rt, store_team(me))
    await owned(store, me, type_id, "publish")
    await store.publish(type_id, body.version, by=by_of(me))
    return ok(detail(await store.get(type_id)))
