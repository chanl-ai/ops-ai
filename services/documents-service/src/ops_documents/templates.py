# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""`/v1/templates`: the document types a team may install from its plugins, and the install that makes the
team's own copy. agents-service serves the same routes for agents, skills and workflows.

tools-service is the one service that loads plugins; it answers the templates of the plugins on for the acting team,
with each body (`GET /v1/plugin-templates`). A copy is made through the document type create route's own model and
`DocumentTypes.create`, so a copy can never be something a person's create would refuse, and it is ready to read at
once (version 1, as create makes it). Where a copy came from is a `template_copies` row; the copy itself is an ordinary
type the team edits like any other.

The routes act in the caller's team (`who` refuses a call naming none), since a copy saved with no team would be every
team's. `source` is `plugin:<plugin id>` now; a built-in pack is another source later, on the same routes."""

# No `from __future__ import annotations`: the routes' `Depends(caller)` annotations name the factory's arguments, which
# FastAPI can only read as objects, not as strings resolved in this module.

import hashlib
import json
from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, ValidationError

from ops_contracts.field_values import DEFAULT_DATE_ORDER
from ops_documents.document_types import DocumentTypes
from ops_documents.extraction import request_of
from ops_documents.files import Who
from ops_documents.models import DocumentTypeIn, DocumentTypeVersionIn, Model
from ops_documents.store import NameTakenError, TemplateCopies
from ops_documents.tools_client import PluginTemplates
from ops_identity import ServiceCallError, ServiceUnreachable
from ops_service_kit.errors import ApiError, Conflict, NotFound, ServiceUnavailable, ValidationFailed
from ops_service_kit.http import Envelope, ok
from ops_service_kit.template_merge import FieldOutcome, apply, merge

Kind = Literal["document_type"]
KIND: Kind = "document_type"
State = Literal["available", "added", "update_available", "removed_upstream"]
# Keys of a template body the copy never takes: the type id is the team's own (ids are unique per tenant, so a body's
# id would collide with another team's copy), and a sample file is one team's file.
NOT_COPIED = ("id", "sampleFileId", "sample_file_id")
# What an update compares, besides each extracted field by its key (`field:<key>`). The name and description are the
# team's; layout templates and the read tuning (page images, offer at) come from the team's own reads and carry forward.
MERGED: dict[str, str] = {
    "many": "reads several records",
    "reviewBelow": "review below",
    "dateOrder": "date order",
    "checks": "checks",
}
FIELD = "field:"


class TemplatePlugin(Model):
    id: str
    title: str
    version: str


class TemplateRequires(Model):
    tools: list[str]
    bind: list[dict[str, str]]
    resources: list[str] = Field(default_factory=list[str])


class Installed(Model):
    # Live copies the team holds of this template, the newest version among them, and whether the source ships a
    # newer one. A copy never changes by itself; updating one is a later card.
    copies: int
    version: int | None
    newer_available: bool
    # The newest live copy was made from a body other than the template's current one (its digest differs).
    changed: bool = False


class CopyRef(Model):
    id: str
    kind: Kind
    record_id: str
    source: str
    template_id: str
    version: int
    # Set once the team detached the copy: it is the team's own and takes no updates.
    detached_at: str | None = None


class AddCell(Model):
    # The roles grid cell a person needs to add this resource, so another service listing it says the same.
    area: str
    action: str


class TemplateView(Model):
    source: str
    plugin: TemplatePlugin
    kind: Kind
    id: str
    version: int
    title: str
    requires: TemplateRequires
    installed: Installed
    # available, added, update_available (the app ships a newer or changed template than the copy was made from), or
    # removed_upstream (the team holds a copy the app, still on, no longer ships).
    state: State
    # Whether the caller's roles let them add it: every member keeps the team's document types (documents.edit).
    can_add: bool
    add_cell: AddCell
    # The cell the copy's delete checks: whoever keeps the team's document types removes one.
    remove_cell: AddCell | None = None
    # The team's newest live copy, which Open and Remove act on.
    copy_: CopyRef | None = Field(default=None, alias="copy")


class InstallInput(Model):
    # The version listed now when left out; another one is 404 template_version_not_found.
    version: int | None = Field(default=None, ge=1)
    # The copy's name; the template's when left out. Unique in the team, as on create (409 name_taken).
    name: str | None = Field(default=None, min_length=1, max_length=200)


class Installation(Model):
    copy_: CopyRef = Field(alias="copy")
    created: bool
    # Bindings the install left for the person; a document type template names none.
    needs: list[dict[str, str]]


class UpdateExpect(Model):
    # The template digest and the type's newest version digest the person reviewed; a take whose either moved is 409.
    digest: str | None = None
    record_digest: str | None = None


class UpdateInput(Model):
    # merge (the default) keeps the team's edits field by field; reset makes the next version from the template and
    # drops them. Left out with `confirm`, the call is a reset: an older console's "take the template as it is".
    mode: Literal["merge", "reset"] | None = None
    # Per conflicting field (`field:<key>`, or many, reviewBelow, dateOrder, checks), which value the update writes; a
    # conflict left out keeps the team's.
    choices: dict[str, Literal["yours", "template"]] = Field(default_factory=dict[str, Literal["yours", "template"]])
    expect: UpdateExpect | None = None
    # For reset: the person saw the edits it drops.
    confirm: bool = False


class FieldReview(Model):
    field: str
    label: str
    # kept: only the team changed it; taken: only the template did; conflict: both did, the team's unless chosen.
    outcome: Literal["kept", "taken", "conflict"]
    yours: Any = None
    template: Any = None


class UpdateReview(Model):
    copy_: CopyRef = Field(alias="copy")
    # The template version the copy was made from, and the one the app ships now.
    from_version: int
    to_version: int
    # Every field the update touches: kept, taken or a choice.
    fields: list[FieldReview] = Field(default_factory=list[FieldReview])
    # A document type has no draft: always false.
    draft_open: bool = False
    # Taking the update makes the type's next version at once (a document type has no draft). Versions a workflow
    # pinned keep reading as they were; a workflow saved after it pins the new one. The dialog says so first.
    applies_now: bool = True
    # What the take names back, so a template or type that moved since this review is refused.
    expect: UpdateExpect = Field(default_factory=UpdateExpect)
    # For older consoles: the fields the update changes, and the fields the team's own edits hold.
    changes: list[str]
    edits: list[str]
    # True once the update was taken; `version` is the type version it made, None when nothing needed saving.
    taken: bool = False
    version: int | None = None


class TemplateNotFound(ApiError):
    status = 404
    code = "template_not_found"


class CopyDetached(ApiError):
    status = 409
    code = "detached"


def _copy_view(row: dict[str, Any]) -> dict[str, Any]:
    keys = ("id", "kind", "record_id", "source", "template_id", "version", "detached_at")
    return CopyRef.model_validate({k: row.get(k) for k in keys}).model_dump(by_alias=True)


def shaped(version: dict[str, Any]) -> dict[str, Any]:
    """The part of a type version an update compares, normalised as the create path saves it, so a template body and
    a stored version of the same content compare equal."""
    request = request_of(
        {"fields": version.get("fields"), "many": version.get("many"), "reviewBelow": version.get("reviewBelow")}
    )
    return {
        "fields": request["fields"],
        "many": request["many"],
        "reviewBelow": request["reviewBelow"],
        "dateOrder": version.get("dateOrder") or DEFAULT_DATE_ORDER,
        "checks": version.get("checks") or [],
    }


def _flat(body: dict[str, Any]) -> dict[str, Any]:
    """A shaped version as the merge reads it: each extracted field under `field:<key>`, so two sides that changed
    different fields never conflict."""
    out = {k: body.get(k) for k in MERGED}
    for f in cast(list[dict[str, Any]], body.get("fields") or []):
        out[FIELD + str(f["key"])] = f
    return out


def _order(*bodies: dict[str, Any] | None) -> list[str]:
    """The merge's field list: the options, then extracted fields in the team's order, then ones only the template or
    the base names."""
    keys = list(MERGED)
    for b in bodies:
        for f in cast(list[dict[str, Any]], (b or {}).get("fields") or []):
            if (k := FIELD + str(f["key"])) not in keys:
                keys.append(k)
    return keys


def _unflat(flat: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    fields = [flat[k] for k in keys if k.startswith(FIELD) and flat.get(k) is not None]
    return {**{k: flat.get(k) for k in MERGED}, "fields": fields}


def _digest(body: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _labelled(outcomes: list[FieldOutcome]) -> list[dict[str, Any]]:
    def label(o: FieldOutcome) -> str:
        if o.field in MERGED:
            return MERGED[o.field]
        named = cast(dict[str, Any], o.yours or o.template or {})
        return f"field {named.get('label') or o.field.removeprefix(FIELD)}"

    return [
        {"field": o.field, "label": label(o), "outcome": o.outcome, "yours": o.yours, "template": o.template}
        for o in outcomes
    ]


def templates_router(
    *,
    copies: TemplateCopies,
    document_types: DocumentTypes,
    caller: Callable[..., Any],
    scope: Callable[[str], Any],
    responses: dict[int | str, dict[str, Any]],
) -> APIRouter:
    """The routes, acting as `caller` resolves the request (documents' `who`) under `scope(action)`. tools-service is
    reached through `app.state.plugin_templates`; with none, both routes answer 503."""
    # No router-wide tag: the list is `templates`, the copy `resources` (Add to team in the screen's words, the
    # same route agents-service answers for agents, skills and workflows), and the first tag names the SDK operation.
    router = APIRouter(responses=responses)

    async def offered(request: Request, who: Who) -> list[dict[str, Any]]:
        """Every resource of the plugins on for the caller's team, from tools-service."""
        tools = cast(PluginTemplates | None, getattr(request.app.state, "plugin_templates", None))
        if tools is None:
            raise ServiceUnavailable("Templates come from tools-service, and this service has no address for it.")
        try:
            return await tools.offered(who)
        except (ServiceCallError, ServiceUnreachable) as e:
            raise ServiceUnavailable(
                "tools-service did not answer with the team's templates. Try again shortly."
            ) from e

    async def listed(request: Request, who: Who) -> list[dict[str, Any]]:
        """The document type templates of the plugins on for the caller's team."""
        return [t for t in await offered(request, who) if t.get("kind") == KIND]

    @router.get(
        "/v1/templates", tags=["templates"], response_model=Envelope[list[TemplateView]], dependencies=[scope("view")]
    )
    async def list_templates(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        who: Annotated[Who, Depends(caller)],
        kind: Annotated[Kind | None, Query()] = None,
    ) -> JSONResponse:
        """The document types the team's plugins bring, each with its state for the team, the copies the team holds of
        it and whether the caller may add it. A copy whose template the app no longer ships, while the app is still on,
        is listed too, as `removed_upstream`; a copy of an app turned off for the team reads `added`."""
        held = await copies.of_team()
        everything = await offered(request, who)
        on_sources = {str(t["source"]) for t in everything}
        shipped: set[tuple[str, str]] = set()
        out: list[dict[str, Any]] = []
        cell = {"area": "documents", "action": "edit"}
        for t in (x for x in everything if x.get("kind") == KIND):
            shipped.add((str(t["source"]), str(t["id"])))
            mine = [c for c in held if c["source"] == t["source"] and c["template_id"] == t["id"]]
            newest = max((int(c["version"]) for c in mine), default=None)
            latest = max(mine, key=lambda c: (int(c["version"]), str(c["installed_at"])), default=None)
            installed = {
                "copies": len(mine),
                "version": newest,
                "newerAvailable": newest is not None and newest < t["version"],
                "changed": latest is not None and bool(t.get("digest")) and latest.get("digest") != t.get("digest"),
            }
            state = (
                "available"
                if not mine
                else "update_available"
                if installed["newerAvailable"] or installed["changed"]
                else "added"
            )
            view = {k: t[k] for k in ("source", "plugin", "kind", "id", "version", "title", "requires")}
            mine_now = _copy_view(latest) if latest else None
            extra = {
                "state": state,
                "canAdd": who.creates,
                "addCell": cell,
                "removeCell": cell if mine_now else None,
                "copy": mine_now,
            }
            out.append(TemplateView.model_validate(view | {"installed": installed} | extra).model_dump(by_alias=True))
        plugins = {str(t["source"]): t["plugin"] for t in everything}
        for c in held:
            at = (str(c["source"]), str(c["template_id"]))
            if at in shipped:
                continue
            name = await document_types.name(who, str(c["record_id"]))
            if name is None:
                continue
            shipped.add(at)
            view: dict[str, Any] = {
                "source": c["source"],
                "plugin": plugins.get(str(c["source"]))
                or {
                    "id": str(c["source"]).removeprefix("plugin:"),
                    "title": str(c["source"]).removeprefix("plugin:"),
                    "version": "",
                },
                "kind": KIND,
                "id": c["template_id"],
                "version": int(c["version"]),
                "title": name,
                "requires": {"tools": [], "bind": []},
                "installed": {"copies": 1, "version": int(c["version"]), "newerAvailable": False, "changed": False},
                "state": "removed_upstream" if c["source"] in on_sources else "added",
                "canAdd": False,
                "addCell": cell,
                "removeCell": cell,
                "copy": _copy_view(c),
            }
            out.append(TemplateView.model_validate(view).model_dump(by_alias=True))
        return ok(out)

    async def make_type(who: Who, t: dict[str, Any], body: InstallInput) -> tuple[str, dict[str, Any]]:
        """The create route's body and path: `DocumentTypeIn`, then `DocumentTypes.create`, which checks the fields as
        an extraction does and makes version 1. Answers the type's id and the base its copy link keeps."""
        fields = {k: v for k, v in cast(dict[str, Any], t.get("body") or {}).items() if k not in NOT_COPIED}
        fields["name"] = body.name or fields.get("name") or t["title"]
        try:
            parsed = DocumentTypeIn.model_validate(fields)
        except ValidationError as e:
            first = e.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise ValidationFailed(
                f"The template is not a document type this service makes: {where}: {first['msg']}"
            ) from None
        asked = parsed.model_dump(mode="json", by_alias=True, exclude={"sample_file_id"})
        try:
            made = await document_types.create(who, asked)
        except NameTakenError as e:
            suggestion = f"{parsed.name}, {t['plugin']['title']}"
            raise Conflict(
                f"Your team already has a document type named {parsed.name}. Add this one under another name, such as "
                f"{suggestion}.",
                code="name_taken",
                details={"suggestion": suggestion},
            ) from e
        return str(made["id"]), shaped(parsed.model_dump(mode="json", by_alias=True))

    @router.post(
        "/v1/resources/{resource}/copies",
        tags=["resources"],
        response_model=Envelope[Installation],
        status_code=201,
        responses={
            200: {"model": Envelope[Installation], "description": "The team already holds a copy of this version"}
        },
        dependencies=[scope("edit")],
    )
    async def copy_resource(  # pyright: ignore[reportUnusedFunction]
        request: Request,
        who: Annotated[Who, Depends(caller)],
        resource: str,
        body: InstallInput,
    ) -> JSONResponse:
        """Add to team: makes the team's own copy of the document type, 201 with it, or 200 with the copy the team
        already holds of this version. `resource` is `<source>:<template id>`; the source has a colon of its own
        (`plugin:<id>`), so the template id follows the last one. 404 `template_not_found` when the team's apps bring
        no such resource, `template_version_not_found` for a version they do not ship."""
        source, _, template_id = resource.rpartition(":")
        t = next((x for x in await listed(request, who) if x["source"] == source and x["id"] == template_id), None)
        if t is None:
            raise TemplateNotFound(
                f"No template {template_id} from {source} for this team; its plugin may be off for it."
            )
        version = int(t["version"])
        if body.version is not None and body.version != version:
            raise TemplateNotFound(
                f"{source} ships {template_id} version {version}, not {body.version}.",
                code="template_version_not_found",
            )
        held = await copies.live(source, template_id)
        if held is not None and await document_types.get(who, str(held["record_id"])) is not None:
            return ok({"copy": _copy_view(held), "created": False, "needs": []})
        # The create path refuses a role that cannot change document types, before anything is written.
        record_id, base = await make_type(who, t, body)
        if held is not None:
            # The old copy's type is gone; its row stops counting so the new copy can be recorded.
            await copies.removed(str(held["id"]))
        row, made = await copies.add(
            team=who.team,
            kind=KIND,
            record_id=record_id,
            source=source,
            template_id=template_id,
            version=version,
            by=who.actor,
            digest=cast(str | None, t.get("digest")),
            # The create path makes version 1; a later version is the team's own.
            record_version=1,
            base=base,
        )
        # Another install of this version won the race: its copy stands, and the type made here stays as an unused type
        # of the team's (this service has no delete for a type). A type's name is unique in its team, so this happens
        # only when the two installs named their copies differently.
        return ok({"copy": _copy_view(row), "created": made, "needs": []}, 201 if made else 200)

    async def review(
        request: Request, who: Who, resource: str, type_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[FieldOutcome], list[str], dict[str, Any]]:
        """The copy's row, its template now, the review of taking it, the merge's outcomes and field list, and the
        template's body shaped as a version. 409 `detached` for a copy the team made its own."""
        source, _, template_id = resource.rpartition(":")
        t = next((x for x in await listed(request, who) if x["source"] == source and x["id"] == template_id), None)
        if t is None:
            raise TemplateNotFound(
                f"No template {template_id} from {source} for this team; its plugin may be off for it."
            )
        row = await copies.of_record(type_id)
        found = await document_types.get(who, type_id)
        if row is None or found is None or row["source"] != source or row["template_id"] != template_id:
            raise NotFound(f"The team's copy {type_id} of {resource}")
        if row.get("detached_at"):
            raise CopyDetached(
                f"Your team detached its copy of {t['title']}, so it takes no updates. Add the template again under "
                "another name for a fresh copy."
            )
        fields = {
            k: v
            for k, v in cast(dict[str, Any], t.get("body") or {}).items()
            if k not in (*NOT_COPIED, "name", "description")
        }
        try:
            parsed = DocumentTypeVersionIn.model_validate(fields)
        except ValidationError as e:
            first = e.errors()[0]
            raise ValidationFailed(
                f"The template is not a document type this service makes: {'.'.join(str(p) for p in first['loc'])}: "
                f"{first['msg']}"
            ) from None
        template = shaped(parsed.model_dump(mode="json", by_alias=True))
        versions = cast(list[dict[str, Any]], found.get("versions") or [])
        newest = max(versions, key=lambda v: int(v["version"]))
        yours = shaped(newest)
        base = cast(dict[str, Any] | None, row.get("base"))
        if base is None and row.get("record_version") is not None:
            # A link made before bases were kept: the version the copy made is the copy as made, when it still exists;
            # otherwise every difference is a choice kept as the team's.
            made = next((v for v in versions if int(v["version"]) == int(row["record_version"])), None)
            base = shaped(made) if made is not None else None
        keys = _order(yours, template, base)
        outcomes = merge(_flat(base) if base is not None else None, _flat(yours), _flat(template), keys)
        view = {
            "copy": _copy_view(row),
            "fromVersion": int(row["version"]),
            "toVersion": int(t["version"]),
            "fields": _labelled(outcomes),
            "appliesNow": True,
            "expect": {"digest": t.get("digest"), "recordDigest": _digest(yours)},
            "changes": [o.field for o in outcomes if o.outcome != "kept"],
            "edits": [o.field for o in outcomes if o.outcome != "taken"],
        }
        return row, t, view, outcomes, keys, template

    @router.get(
        "/v1/resources/{resource}/copies/{copy}/update",
        tags=["resources"],
        response_model=Envelope[UpdateReview],
        dependencies=[scope("view")],
    )
    async def review_update(  # pyright: ignore[reportUnusedFunction]
        request: Request, who: Annotated[Who, Depends(caller)], resource: str, copy: str
    ) -> JSONResponse:
        """Review update: field by field, what taking the app's current template does to the team's type (`copy` is the
        type's id): the team's edits kept, the template's changes taken, and the fields both changed, which keep the
        team's value unless the person chooses. Each extracted field is compared by its key. 409 `detached` for a copy
        the team made its own."""
        _, _, view, _, _, _ = await review(request, who, resource, copy)
        return ok(UpdateReview.model_validate(view).model_dump(by_alias=True))

    @router.post(
        "/v1/resources/{resource}/copies/{copy}/update",
        tags=["resources"],
        response_model=Envelope[UpdateReview],
        dependencies=[scope("edit")],
    )
    async def take_update(  # pyright: ignore[reportUnusedFunction]
        request: Request, who: Annotated[Who, Depends(caller)], resource: str, copy: str, body: UpdateInput
    ) -> JSONResponse:
        """Take update. `merge` (the default) makes the type's next version keeping every field the team edited,
        taking every field only the template changed, and writing the template's value on a conflict only where
        `choices` says so; `reset` makes it from the template as it is, after `confirm` (409 `copy_edited` listing the
        edits it drops). A document type has no draft, so the version applies at once; earlier versions, and every pin
        on them, stay. 409 `update_stale` when the template or the type moved since the review `expect` names, and
        nothing is saved; 409 `detached` for a copy the team made its own."""
        row, t, view, outcomes, keys, template = await review(request, who, resource, copy)
        if body.expect is not None and (
            body.expect.digest != view["expect"]["digest"]
            or body.expect.record_digest != view["expect"]["recordDigest"]
        ):
            raise Conflict(
                f"{t['title']} changed since you reviewed this update. Review it again before taking it.",
                code="update_stale",
            )
        mode = body.mode or ("reset" if body.confirm else "merge")
        kept = [o.field for o in outcomes if o.outcome != "taken"]
        if mode == "reset" and kept and not body.confirm:
            raise Conflict(
                f"Your team changed {t['title']} since adding it ({', '.join(kept)}). Resetting makes a new version "
                "from the app's template, without those changes. Confirm to reset.",
                code="copy_edited",
                details=view,
            )
        found = await document_types.get(who, copy)
        assert found is not None
        newest = max(cast(list[dict[str, Any]], found["versions"]), key=lambda v: int(v["version"]))
        yours = _flat(shaped(newest))
        choices = {o.field: "template" for o in outcomes} if mode == "reset" else dict(body.choices)
        merged = _flat(template) if mode == "reset" else apply(yours, outcomes, cast(dict[str, Any], choices))
        taken = [o.field for o in outcomes if o.outcome == "taken"]
        chosen = [o.field for o in outcomes if o.outcome == "conflict" and choices.get(o.field) == "template"]
        note = (
            f"Update from {t['plugin']['title']}, template version {t['version']}: "
            f"kept {', '.join(o.field for o in outcomes if o.outcome == 'kept') or 'none'}; "
            f"taken {', '.join(taken) or 'none'}; chosen from the template {', '.join(chosen) or 'none'}"
        )[:500]
        version: int | None = None
        if merged != yours:
            made = await document_types.add_version(who, copy, _unflat(merged, keys) | {"note": note})
            if made is None:
                raise NotFound(f"Document type {copy}")
            version = int(made["version"])
        await copies.updated(
            str(row["id"]),
            version=int(t["version"]),
            digest=cast(str | None, t.get("digest")),
            record_version=version if version is not None else int(row.get("record_version") or newest["version"]),
            base=template,
        )
        refreshed = await copies.of_record(copy)
        out = view | {"copy": _copy_view(refreshed or row), "taken": True, "version": version}
        return ok(UpdateReview.model_validate(out).model_dump(by_alias=True))

    @router.post(
        "/v1/resources/{resource}/copies/{copy}/detach",
        tags=["resources"],
        response_model=Envelope[CopyRef],
        dependencies=[scope("edit")],
    )
    async def detach_copy(  # pyright: ignore[reportUnusedFunction]
        who: Annotated[Who, Depends(caller)], resource: str, copy: str
    ) -> JSONResponse:
        """Detach: the team's type becomes its own, offered no update again, and the template is offered for a fresh
        copy. Its versions are unchanged. A second call answers the same copy. 404 when `copy` is not the team's copy
        of `resource`."""
        source, _, template_id = resource.rpartition(":")
        row = await copies.of_record(copy)
        if row is None or row["source"] != source or row["template_id"] != template_id:
            raise NotFound(f"The team's copy {copy} of {resource}")
        # Detaching changes the team's type as an edit does: the same documents.edit check.
        document_types.may_change(who)
        return ok(_copy_view(await copies.detach(str(row["id"]), by=who.actor)))

    return router
