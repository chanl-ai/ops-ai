"""`/v1/case-types`: the fields a case shows and their order (c-291), versioned like task types.

Every member of the tenant reads every type. Creating, saving and publishing one are workflow building
(`workflows.create`, `workflows.edit`, `workflows.publish`) in the owning team; a seeded type is a system record, and a
team copies it to change it. A case pins the version it was opened with."""

from __future__ import annotations

import re
from typing import Annotated, Any, TypeAlias, cast

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import Field

from ops_access import can
from ops_contracts.chat import WireModel
from ops_service_kit.errors import Unprocessable
from ops_service_kit.http import Envelope

from ...case_fields import specs_of
from ..auth import Principal, caller_in, caller_of
from ..case_type_seeds import case_type_store
from ..deps import Runtime, runtime
from ..envelope import ok
from ..typed_record_routes import RecordTypeView, RecordVersionView, by_of, detail, owned, team_of, view

Rt: TypeAlias = Annotated[Runtime, Depends(runtime)]  # noqa: UP040 - FastAPI reads Annotated aliases
Me: TypeAlias = Annotated[Principal, Depends(caller_in("workflows"))]  # noqa: UP040

router = APIRouter(prefix="/v1/case-types")
ID = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


class CaseField(WireModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=200)
    # text, number, money, date, enum (the extraction field types), file or link.
    type: str = "text"
    required: bool = False
    options: list[str] | None = None


class Definition(WireModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    fields: list[CaseField] = Field(max_length=50)
    # The key of one of the type's date fields whose value is the case's deadline, its main timer (c-500): a court
    # notice's date to respond by, read from the notice. None: the case's resolution clock.
    deadline: str | None = Field(default=None, max_length=64)


class TypeRef(WireModel):
    id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)


class TypeIn(WireModel):
    id: str = Field(min_length=3, max_length=64)
    # Start from this type's published version (the newest when no version); the fields below replace its own.
    copy_of: TypeRef | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    fields: list[CaseField] | None = Field(default=None, max_length=50)
    deadline: str | None = Field(default=None, max_length=64)


class PublishIn(WireModel):
    version: int = Field(ge=1)


class CaseTypeView(RecordTypeView):
    pass


class CaseTypeVersionView(RecordVersionView):
    pass


class CaseTypeDetail(CaseTypeView):
    versions: list[CaseTypeVersionView]


def _checked(content: dict[str, Any]) -> dict[str, Any]:
    specs_of(content.get("fields") or [])
    deadline = content.get("deadline")
    if deadline is not None:
        fields = cast(list[dict[str, Any]], content.get("fields") or [])
        dates = {str(f.get("key")) for f in fields if f.get("type") == "date"}
        if deadline not in dates:
            raise Unprocessable(
                f"deadline must name one of this type's date fields; {deadline} is not one.", code="deadline_field"
            )
    return content


@router.get("", response_model=Envelope[list[CaseTypeView]])
async def list_case_types(rt: Rt, me: Me) -> JSONResponse:
    """Every case type in the tenant: the seeded ones first, then the teams' own."""
    return ok([view(r) for r in await (await case_type_store(rt)).rows()])


@router.get("/{type_id}", response_model=Envelope[CaseTypeDetail])
async def get_case_type(rt: Rt, me: Me, type_id: str) -> JSONResponse:
    """A case type with each of its versions, newest first."""
    return ok(detail(await (await case_type_store(rt)).get(type_id)))


@router.post("", response_model=Envelope[CaseTypeDetail], status_code=201)
async def create_case_type(rt: Rt, me: Me, body: TypeIn) -> JSONResponse:
    """A team's case type as draft v1: from nothing, or a copy of another type's published version with edits."""
    team = team_of(me, "case type")
    can(caller_of(me), "workflows", "create", team=team, what="a case type")
    if not ID.match(body.id):
        raise Unprocessable("id: lowercase letters, digits and underscores, starting with a letter.", code="invalid_id")
    store = await case_type_store(rt)
    base: dict[str, Any] = {}
    copied: dict[str, Any] | None = None
    if body.copy_of is not None:
        n, base = await store.published(body.copy_of.id, body.copy_of.version)
        copied = {"id": body.copy_of.id, "version": n}
    given = body.model_dump(mode="json", exclude={"id", "copy_of"}, exclude_none=True)
    content = _checked({"fields": [], **base, **given})
    if not content.get("name"):
        raise Unprocessable("name is required.", code="case_type_invalid")
    await store.create(body.id, content, team_id=team, by=by_of(me), copied_from=copied)
    return ok(detail(await store.get(body.id)), 201)


@router.put("/{type_id}/draft", response_model=Envelope[CaseTypeDetail])
async def save_case_type(rt: Rt, me: Me, type_id: str, body: Definition) -> JSONResponse:
    """Saves the draft: edits it in place, or opens the next version over a published one."""
    store = await case_type_store(rt)
    await owned(store, me, type_id, "edit")
    await store.save_draft(type_id, _checked(body.model_dump(mode="json", exclude_none=True)), by=by_of(me))
    return ok(detail(await store.get(type_id)))


@router.post("/{type_id}/publish", response_model=Envelope[CaseTypeDetail])
async def publish_case_type(rt: Rt, me: Me, type_id: str, body: PublishIn) -> JSONResponse:
    """Publishes the newest draft. Cases already open keep the version they were opened with."""
    store = await case_type_store(rt)
    await owned(store, me, type_id, "publish")
    await store.publish(type_id, body.version, by=by_of(me))
    return ok(detail(await store.get(type_id)))
