# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Extraction (moved to documents-service): a clean file and a schema in, every field back with its
value, confidence, page, quote and whether a person must check it. The workflow step, agents and outside callers all
ask here, so they get one answer.

The file is parsed into pages (ops_ingest), the model is asked once through models-service (and once more with the
schema errors), and each field is scored by ops_extract's checks against the field's, the schema's and the workspace
floor: the model never sets a confidence. A file of up to `SYNC_PAGES` pages and `SYNC_BYTES` bytes is answered at
once; a larger one is queued, runs as a task in this process with its status on its row, and is picked up again when
documents-service restarts (`resume`), so a restart never loses one."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from functools import partial
from typing import Any, Protocol, TypedDict, cast

import httpx
import regex

from ops_access import team_off, team_on
from ops_contracts import readings as readings_contract
from ops_contracts.field_values import FIELD_TYPES
from ops_documents.errors import IdempotencyConflictError, InvalidRequestError, StateError
from ops_documents.files import Files, Who
from ops_documents.pending import Pending
from ops_documents.readings import READING_PROCESS, SYNC_BYTES, SYNC_PAGES, Readings, settings_of
from ops_documents.store import ExtractionRow, ExtractionsStore
from ops_documents.store.document_types import SINGLE
from ops_documents.store.extractions import CorrectedEvent, NewExample, file_read
from ops_extract import boxes, classify, page_images, prompt, result, rules, templates
from ops_extract.checks import CLEAN_RULES, DEFAULT_FLOOR, in_quote, threshold
from ops_extract.floor import FloorUnreadError, PlatformFloor
from ops_extract.layout import layout_of, page_text
from ops_extract.pages import Pages
from ops_extract.shapes import Box, Check, DocumentKind, FieldDefinition, Layout, SavedTemplate
from ops_files_client import FileInfo
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_ingest.reading import Reading, read
from ops_service_kit import narrow
from ops_service_kit.http import Json, JsonList, JsonValue
from ops_service_kit.listing import ListParams
from ops_service_kit.logging import get_logger
from ops_service_kit.model_calls import ENDINGS, ModelCallError, ModelCalls
from ops_service_kit.model_calls import Usage as CallUsage
from ops_service_kit.narrow import Malformed, a_list, an_object, entries, required
from ops_service_kit.settings import Settings
from ops_store import background, isolation
from ops_store.documents import stored
from ops_store.listing import ListPage

log = get_logger("ops_documents.extraction")

ALIAS = "extract"


# models-service's refusals a person can act on, as the read's error: a spent budget waits for its reset, a busy model
# for a minute. Anything else reads as the model being out of reach.
SPENT = "The team's model budget is spent; reads that call a model wait until it resets."
REFUSALS = {
    "key_budget_exhausted": ("budget_exhausted", SPENT),
    "tenant_budget_exhausted": ("budget_exhausted", SPENT),
    "rate_limited": ("model_rate_limited", "The model is busy; try again in a minute."),
    "models_answer_unreadable": ("model_answer_unreadable", "The model's answer could not be read; try again."),
    # A reply billed but holding no answer: the read fails with why, and no field is saved from it.
    "reply_cut_off": (
        "reply_cut_off",
        "The model's reply was cut off at its length limit. Read fewer fields, or raise OPS_EXTRACT_OUTPUT_TOKENS.",
    ),
    "reply_declined": ("reply_declined", "The model declined to read this file."),
    "reply_filtered": ("reply_filtered", "The provider's content filter stopped the model's reply."),
    "reply_empty": ("reply_empty", "The model's reply held no answer. Try again, or read fewer fields."),
    "models_timeout": ("model_late", "The model did not answer in time."),
    "provider_timeout": ("model_late", "The model did not answer in time."),
}
READS = ("fields", "propose")
PROPOSE_PAGES = 5


@dataclass
class Usage(CallUsage):
    """The model's calls and tokens over an extraction (the first ask and any re-ask), as models-service bills them,
    with what extraction keeps about page images."""

    # Every call that carried a page image: {step, pages, images, alias}, kept on the read.
    image_calls: JsonList = field(default_factory=JsonList)
    # Why an image was not sent though the read allowed it: the alias is not cleared for images.
    image_refused: str | None = None


class Models(Protocol):
    async def structured(
        self,
        system: str,
        user: str,
        schema: Json,
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Usage | None = None,
        images: Sequence[page_images.PageImage] = (),
    ) -> JsonValue: ...


class Floors(Protocol):
    async def floor(self, tenant: str, team: str) -> float: ...


class PageImagePolicy(Protocol):
    async def allowed(self, tenant: str, team: str) -> bool:
        """Whether the team's pageImages policy lets its reads show the model page images."""
        ...


# How a read was made: from a layout template's zones or by the model.
PATH_TEMPLATE = "template"
PATH_MODEL = "model"

# Reported when a person corrects a field (documents-service owns extraction.* events).
CORRECTED_EVENT = "extraction.corrected"


class ResolvedVersion(TypedDict):
    """A team's document type version as an extraction reads with it (`DocumentTypes.resolve`)."""

    id: str
    name: str
    version: int
    fields: list[Json]
    many: bool
    reviewBelow: float | None
    # The templates extraction tries: every one but those flagged for a rebuild.
    templates: list[Json]
    allTemplates: list[Json]
    checks: list[Json]
    pageImages: bool
    offerAt: int


class TypeResolver(Protocol):
    async def resolve(self, who: Who, type_id: str, version: int | None) -> ResolvedVersion:
        """{id, name, version, fields, many, reviewBelow} of a team's document type version."""
        ...

    async def list(self, who: Who) -> Sequence[DocumentKind]:
        """The team's document types: {id, name, description, latestVersion}, which classification reads."""
        ...

    async def name(self, who: Who, type_id: str) -> str | None:
        """One of the team's document types' name, or None when the team has no such type."""
        ...

    async def examples(self, tenant: str, team: str, type_id: str, keys: list[str]) -> list[Json]:
        """The type's recent examples for the fields a read asks: field, printed line and value."""
        ...


@dataclass
class ModelsService:
    """Extraction's model calls on the one client (`ops_service_kit.model_calls`), with documents-service's own model
    key (`purpose:extract`, with its own budget), so this service holds no provider key. `extract` falls back to
    `default` while models-service has no such alias. What is extraction's own is what it does with a page image: an
    alias not cleared for images reads on with the text alone and says why, and every call that carried one is kept."""

    http: httpx.AsyncClient
    key: str
    alias: str = ALIAS
    # The most tokens the model may write in one reply; the default is Settings.extract_output_tokens's.
    output_tokens: int = Settings.model_fields["extract_output_tokens"].default

    async def structured(
        self,
        system: str,
        user: str,
        schema: Json,
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Usage | None = None,
        images: Sequence[page_images.PageImage] = (),
    ) -> JsonValue:
        spent = usage if usage is not None else Usage()

        def ask(alias: str) -> partial[Any]:
            # The tenant spends from its own share of this key, so one tenant cannot drain the others.
            calls = ModelCalls(self.http, self.key, alias)
            return partial(calls.structured, system, user, schema, tenant=tenant, step=step,
                           run=run, usage=spent, max_tokens=self.output_tokens)  # fmt: skip

        try:
            answer = await ask(self.alias)(parts=[i.part() for i in images])
        except ModelCallError as e:
            if not images or e.code != "images_not_cleared":
                raise
            refused = e.alias or self.alias
            spent.image_refused = f"The model alias {refused} is not cleared for page images."
            # Asked again on the alias that refused, so an unbound alias is not looked up a second time.
            return cast(JsonValue, await ask(refused)())
        if images:
            pages: JsonList = [*sorted({i.page for i in images})]
            spent.image_calls.append({"step": step, "pages": pages, "images": len(images), "alias": spent.alias})
        return cast(JsonValue, answer)


@dataclass
class PlatformFloors:
    """The workspace floor (platform-service's extractionFloor policy), read per extraction with this service's token
    for the extraction's tenant and team; an unreadable floor raises FloorUnreadError (ops_extract.floor)."""

    client: Callable[[str, str], ServiceClient]

    async def floor(self, tenant: str, team: str) -> float:
        return await PlatformFloor(self.client(tenant, team)).extraction_floor()


PAGE_IMAGES_POLICY = "pageImages"
# The team's switch for personal data in what people see from AI, which covers document examples too.
MASKING_POLICY = "aiStepsMaskPersonalData"


class MaskingPolicy(Protocol):
    async def masks(self, tenant: str, team: str) -> bool:
        """Whether people in the team see personal data masked; masked unless the team turned it off."""
        ...


@dataclass
class PlatformMasking:
    """The team's aiStepsMaskPersonalData policy, read live: masked unless the team set false, and masked when the
    policy cannot be read, so a failed read never shows a number in full."""

    client: Callable[[str, str], ServiceClient]

    async def masks(self, tenant: str, team: str) -> bool:
        try:
            found = await self.client(tenant, team).get(f"/v1/policies/{MASKING_POLICY}")
        except (ServiceCallError, ServiceUnreachable):
            return True
        return not team_off(an_object(found or {}, f"the {MASKING_POLICY} policy").get("value"), team)


@dataclass
class PlatformPageImages:
    """The team's pageImages policy, read live from platform-service on each read that could send an image. A
    policy that cannot be read counts as off: a failed read must never send a page."""

    client: Callable[[str, str], ServiceClient]

    async def allowed(self, tenant: str, team: str) -> bool:
        try:
            found = await self.client(tenant, team).get(f"/v1/policies/{PAGE_IMAGES_POLICY}")
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("pageImages policy unread; no page image is sent", extra={"tenant": tenant, "error": str(e)})
            return False
        return team_on(an_object(found or {}, f"the {PAGE_IMAGES_POLICY} policy").get("value"), team)


@dataclass
class Pictures:
    """A read's page images, drawn only when one is about to be sent and only after the team's policy allows it, so a
    read with nothing in doubt never fetches the file again or asks platform-service."""

    load: Callable[[], Awaitable[bytes]]
    mime: str
    allow: Callable[[], Awaitable[bool]]
    _allowed: bool | None = None
    _data: bytes | None = None
    _drawn: dict[int, Any] = field(default_factory=dict[int, Any])

    async def allowed(self) -> bool:
        if self._allowed is None:
            self._allowed = await self.allow()
        return self._allowed

    async def _page(self, n: int) -> Any:
        if n not in self._drawn:
            if self._data is None:
                self._data = await self.load()
            self._drawn |= await asyncio.to_thread(page_images.render, self._data, self.mime, [n])
        return self._drawn.get(n)

    async def whole(self, pages: Sequence[int]) -> list[page_images.PageImage]:
        """Whole pages, at most MAX_PAGES of them, or none when the policy says no."""
        if not pages or not await self.allowed():
            return []
        out: list[page_images.PageImage] = []
        for n in list(pages)[: page_images.MAX_PAGES]:
            if (image := await self._page(n)) is not None:
                out.append(page_images.whole(n, image))
        return out

    async def crops(self, boxed: dict[str, list[Box]]) -> dict[str, page_images.PageImage]:
        """Per field, the part of its page around its boxes, or none when the policy says no."""
        if not boxed or not await self.allowed():
            return {}
        out: dict[str, page_images.PageImage] = {}
        for key, found in boxed.items():
            page = found[0]["page"]
            if (image := await self._page(page)) is not None:
                out[key] = page_images.crop(page, image, [b for b in found if b["page"] == page])
        return out


# Why a field read below its threshold is read again with its crop, as a re-read is told.
LOW_CONFIDENCE = "was read with too little confidence to trust"


def fingerprint_of(out: Json, layout: Layout) -> str:
    """A single-record read's layout without its values, from the boxes its fields were found in."""
    fields = an_object(out.get("fields") or {}, "fields")
    found = {k: boxes.boxes_of(an_object(f, f"field {k}").get("boxes")) for k, f in fields.items()}
    return templates.fingerprint(templates.Read(layout, found))


def _recorded(out: Json, usage: Usage) -> None:
    """Every call that carried a page image, and why one was not sent, on the read."""
    if usage.image_calls:
        out["imageCalls"] = usage.image_calls
    if usage.image_refused:
        out["imageRefused"] = usage.image_refused


def _whole(value: JsonValue, what: str) -> int:
    """A count (billed tokens, a page or token limit) as `int()` reads it: "2" and 2.0 count; None, a list or an
    object is not a number and fails the call."""
    if not isinstance(value, int | float | str):
        raise TypeError(f"{what} {value!r} is not a number")
    return int(value)


def _confidence(result: Json) -> float:
    """A field's stored confidence as `float()` reads it: missing or empty is 0.0, and "0.9" reads; a list or an
    object is not a number and fails the correction."""
    value = result.get("confidence") or 0.0
    if not isinstance(value, int | float | str):
        raise TypeError(f"confidence {value!r} is not a number")
    return float(value)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _check_rules(field: Json) -> None:
    """A field's own rules are refused when saved, not when a value meets them: a pattern that does not
    compile, emptyWhen that is not a short list of phrases, or a cleanup rule that is not one of CLEAN_RULES."""
    pattern = field.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str) or not pattern or len(pattern) > 200:
            raise InvalidRequestError(
                f"field {field['key']}: pattern is a regular expression of at most 200 characters"
            )
        try:
            regex.compile(pattern)
        except regex.error as e:
            raise InvalidRequestError(f"field {field['key']}: pattern does not compile: {e}") from e
    phrases = field.get("emptyWhen")
    if phrases is not None and (
        not isinstance(phrases, list)
        or len(cast(list[Any], phrases)) > 20
        or not all(isinstance(p, str) and 0 < len(p) <= 200 for p in cast(list[Any], phrases))
    ):
        raise InvalidRequestError(f"field {field['key']}: emptyWhen is a list of up to 20 phrases")
    if "keyField" in field and not isinstance(field["keyField"], bool):
        raise InvalidRequestError(f"field {field['key']}: keyField is true or false")
    rules = field.get("clean")
    if rules is not None and (not isinstance(rules, list) or not all(r in CLEAN_RULES for r in cast(list[Any], rules))):
        raise InvalidRequestError(f"field {field['key']}: clean lists rules from {', '.join(CLEAN_RULES)}")


def _key_hash(who: Who, key: str) -> str:
    return _sha(f"{who.tenant_id}\n{who.team}\n{who.actor}\n{key}")


# What a stored request holds, read as the shapes `request_of` and the version's checks let it be saved as.
FIELD = stored(FieldDefinition)
CHECK = stored(Check)
TEMPLATE = stored(SavedTemplate)


def fields_of(request: Json) -> list[FieldDefinition]:
    """The fields a stored request asks for; one that is not an object, or has no text key, fails the read."""
    return [FIELD(f) for f in entries(request.get("fields"))]


def review_below(request: Json) -> float | None:
    """The confidence below which a stored request's fields wait for a person; a value that is not one fails the read,
    as the scorer would."""
    return None if request.get("reviewBelow") is None else required(request, "reviewBelow", float)


def request_of(body: Json) -> Json:
    """The extraction asked for, checked: fields with a key and a known type, and the options that change the answer.
    A full-text or proposed read names no fields."""
    read = body.get("read") or "fields"
    if read not in READS:
        raise InvalidRequestError(f"read is one of {', '.join(READS)}")
    fields = body.get("fields") if read == "fields" else []
    if not isinstance(fields, list) or (read == "fields" and not fields):
        raise InvalidRequestError("fields is a list of at least one field")
    keys: set[str] = set()
    for one in fields:
        key = one.get("key") if isinstance(one, dict) else None
        if not isinstance(one, dict) or not isinstance(key, str):
            raise InvalidRequestError("every field has a key")
        if (one.get("type") or "text") not in FIELD_TYPES:
            raise InvalidRequestError(f"field {key} has type {one.get('type')!r}; types are {', '.join(FIELD_TYPES)}")
        if key in keys:
            raise InvalidRequestError(f"field {key} is named twice")
        keys.add(key)
        _check_rules(one)
    below = body.get("reviewBelow")
    if below is not None and (isinstance(below, bool) or not isinstance(below, int | float) or not 0 <= below <= 1):
        raise InvalidRequestError("reviewBelow is a confidence between 0 and 1")
    request: Json = {
        "fields": fields,
        "many": bool(body.get("many")),
        "ocr": bool(body.get("ocr")),
        "reviewBelow": float(below) if below is not None else None,
    }
    if body.get("documentType"):
        request["documentType"] = body["documentType"]
    if body.get("classification"):
        request["classification"] = body["classification"]
    if body.get("templates"):
        # The type version's layout templates, tried before the model.
        request["templates"] = body["templates"]
    if body.get("checks"):
        # The type version's checks across fields, run after scoring.
        request["checks"] = body["checks"]
    if body.get("pageImages"):
        # The type version lets reads show the model page images, still under the team's policy and the alias.
        request["pageImages"] = True
    if read != "fields":
        request["read"] = read
    for name in ("hint", "proposePages", "maxPages", "maxTokens"):
        if body.get(name) is not None:
            request[name] = body[name]
    return request


def answer_of(row: ExtractionRow) -> Json:
    """What a caller reads: the id and status, then the scored answer once done (or what the file had when it could
    not be read), or the error once failed."""
    out: Json = {"id": row.id, "fileId": row.file_id, "status": row.status}
    if row.status in ("done", "unreadable") and row.result is not None:
        out |= {"outcome": row.outcome, **row.result}
    if row.status == "failed":
        out["error"] = {"code": row.error_code, "message": row.error, **(row.result or {})}
    if row.request.get("documentType"):
        out["documentType"] = row.request["documentType"]
    if row.request.get("classification"):
        out["classification"] = row.request["classification"]
    return out


@dataclass
class Extractor:
    files: Files
    store: ExtractionsStore
    models: Models | None
    floors: Floors | None
    alias: str = ALIAS
    types: TypeResolver | None = None
    # The stored readings extraction reads; without them (a test app) each extraction reads the file itself.
    readings: Readings | None = None
    # The team's pageImages policy; without it no read sends a page image.
    page_image_policy: PageImagePolicy | None = None
    # The team's masking of personal data in what people see; without it, masked.
    masking: MaskingPolicy | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _pending: Pending = field(default_factory=Pending)

    async def ask(
        self,
        who: Who,
        file_id: str,
        body: Json,
        *,
        idempotency_key: str | None = None,
        inline: bool = False,
    ) -> tuple[int, Json]:
        """(200, the answer) when it ran now or had already finished, (202, its id and status) when it runs later.
        `inline` runs it now whatever the file's size (a document type's test, already running as a task). A request
        naming `documentTypeId` reads with that type's version (the newest when `version` is not given); one asking
        `detect` classifies the file over the team's types first, and reads with the kind it found, or
        answers outcome unknown, for a person, when no kind fits or the model is less sure than the floor."""
        if body.get("detect") and not body.get("documentTypeId") and not body.get("fields"):
            if idempotency_key is not None:
                held = await self.store.held(_key_hash(who, idempotency_key))
                if held is not None and held.status != "failed":
                    # A retried step reads the first answer; it never pays for a second classification.
                    return (200 if held.status not in ("queued", "running") else 202), answer_of(held)
            file = await self.files.readable(who, file_id)
            found = await self.classify(who, file, ocr=bool(body.get("ocr")))
            if found["typeId"] is None or found["needsReview"]:
                return 200, await self._unknown(who, file, found, body, idempotency_key)
            kept = {k: v for k, v in body.items() if k not in ("detect", "version")}
            typed: Json = {"documentTypeId": found["typeId"], "classification": found}
            body = kept | typed
        if body.get("documentTypeId"):
            if self.types is None:
                raise InvalidRequestError("document types are not served here")
            version = body.get("version")
            if version is not None and (isinstance(version, bool) or not isinstance(version, int)):
                raise InvalidRequestError("version is a whole number")
            t = await self.types.resolve(who, str(body["documentTypeId"]), version)
            below = body.get("reviewBelow")
            body = {
                "fields": [*t["fields"]],
                "many": t["many"],
                "ocr": body.get("ocr"),
                "reviewBelow": below if below is not None else t["reviewBelow"],
                # The name travels with the read, so a workflow's Extract step records it on the file.
                "documentType": {
                    "id": t["id"],
                    "version": t["version"],
                    **({"name": t["name"]} if t.get("name") else {}),
                },
                **({"classification": body["classification"]} if body.get("classification") else {}),
                **({"templates": [*t["templates"]]} if t.get("templates") else {}),
                **({"checks": [*t["checks"]]} if t.get("checks") else {}),
                **({"pageImages": True} if t.get("pageImages") else {}),
            }
        request = request_of(body)
        row = await self.files.readable(who, file_id)
        extraction_id = f"ext_{uuid.uuid4().hex[:16]}"
        request_hash = _sha(json.dumps({"file": file_id, **request}, sort_keys=True))
        key = idempotency_key if idempotency_key is not None else extraction_id
        # Gate: the row saved, or the one the key holds queued again, committed before the file is read or a task
        # picks it up.
        async with isolation.request_transaction():
            held = await self.store.insert(
                {
                    "id": extraction_id,
                    "tenant_id": who.tenant_id,
                    "team": who.team,
                    "file_id": file_id,
                    "file_digest": row.digest or "",
                    "request": request,
                    "schema_digest": _sha(json.dumps(request["fields"], sort_keys=True)),
                    "alias": self.alias,
                    "status": "queued",
                    "attempts": 0,
                    "key_hash": _key_hash(who, key),
                    "request_hash": request_hash,
                    "type_id": an_object(request.get("documentType") or {}, "documentType").get("id"),
                    "asked_by": who.actor,
                    "asked_at": self.clock(),
                }
            )
            # A retry after the floor or the model was out of reach runs it again; a schema error stays the answer.
            again = (
                held.id != extraction_id
                and held.request_hash == request_hash
                and held.status == "failed"
                and held.error_code != "schema_error"
            )
            if again:
                held = await self.store.requeue(held.id)
        if held.id != extraction_id and not again:
            if held.request_hash != request_hash:
                raise IdempotencyConflictError("this Idempotency-Key was used for a different extraction")
            return (200 if held.status not in ("queued", "running") else 202), answer_of(held)
        try:
            pages = None
            if inline or row.size <= SYNC_BYTES:
                pages = await self._pages(who, row, request)
            if not inline and (pages is None or pages.count > SYNC_PAGES):
                await self._later(held)
                return 202, answer_of(held)
            assert pages is not None  # parsed above whenever the extraction runs now
            return 200, answer_of(await self._run(held, row, pages))
        except BaseException as e:
            # A read this request started and did not finish (an error, the request cancelled, its task not
            # started) is settled as failed, not left queued or running: a retry with the same key then runs again
            # now, where a pending row would answer 202 until a restart resumed it.
            await self._cut_off(held.id, e)
            raise

    async def _cut_off(self, extraction_id: str, cause: BaseException) -> None:
        """Settles a still-pending extraction as failed. Shielded, so a second cancel cannot leave it half settled,
        and a failure to settle is logged rather than raised over the cause."""
        error = str(cause) or f"the read was cut off ({type(cause).__name__})"

        async def settle() -> None:
            row = await self.store.get(extraction_id)
            if row is not None and row.status in ("queued", "running"):
                await self.store.finish(
                    extraction_id, status="failed", at=self.clock(), error_code="failed", error=error
                )

        try:
            await asyncio.shield(settle())
        except Exception as e:
            log.warning("extraction_not_settled", extraction=extraction_id, error=str(e))

    async def classify(self, who: Who, file: FileInfo, *, ocr: bool) -> Json:
        """Which of the team's document types the file is (the model's answer over each type's name and
        description): {typeId, name, confidence, reason, needsReview, floor}; typeId null when none fits."""
        if self.types is None:
            raise InvalidRequestError("document types are not served here")
        if self.models is None:
            raise StateError("documents-service has no models-service key")
        types = await self.types.list(who)
        floor = await self.floors.floor(who.tenant_id, who.team) if self.floors is not None else DEFAULT_FLOOR
        pages = await self._pages(who, file, {"ocr": ocr})
        if not types or not pages.texts:
            why = "The team has no document types." if not types else "The file has no readable text."
            return classify.classification({"reason": why}, types, floor)
        ids = [str(t["id"]) for t in types]
        schema = classify.schema(ids)
        user = classify.prompt(types, pages.texts)
        run = f"cls_{uuid.uuid4().hex[:16]}"
        try:
            answer = await self.models.structured(
                classify.SYSTEM, user, schema, run=run, step="classify", tenant=who.tenant_id
            )
        except ModelCallError as e:
            # A reply that held no answer names no type, so the file goes to a person; an outage still fails.
            if e.code not in ENDINGS:
                raise
            return classify.classification({"reason": REFUSALS[e.code][1]}, types, floor)
        if prompt.schema_errors(answer, schema):
            return classify.classification({"reason": "The model's answer named no listed type."}, types, floor)
        # The schema check above proves an object.
        return classify.classification(an_object(answer, "the model's answer"), types, floor)

    async def _unknown(self, who: Who, file: FileInfo, found: Json, body: Json, idempotency_key: str | None) -> Json:
        """A detect read whose kind is unknown or doubtful: recorded done with outcome unknown and no fields, so the
        workflow sends it to a person instead of reading it with the wrong type's fields."""
        request: Json = {
            "fields": [],
            "many": False,
            "ocr": bool(body.get("ocr")),
            "reviewBelow": None,
            "detect": True,
            "classification": found,
        }
        extraction_id = f"ext_{uuid.uuid4().hex[:16]}"
        key = idempotency_key if idempotency_key is not None else extraction_id
        # Saved, finished and read back in one transaction: nothing is asked between them.
        async with isolation.request_transaction():
            held = await self.store.insert(
                {
                    "id": extraction_id,
                    "tenant_id": who.tenant_id,
                    "team": who.team,
                    "file_id": file.id,
                    "file_digest": file.digest or "",
                    "request": request,
                    "schema_digest": _sha("[]"),
                    "alias": self.alias,
                    "status": "queued",
                    "attempts": 0,
                    "key_hash": _key_hash(who, key),
                    "request_hash": _sha(json.dumps({"file": file.id, **request}, sort_keys=True)),
                    "type_id": None,
                    "asked_by": who.actor,
                    "asked_at": self.clock(),
                }
            )
            if held.id != extraction_id:
                return answer_of(held)
            result: Json = {"fileId": file.id, "fields": {}, "needsReview": ["documentType"], "classification": found}
            await self.store.finish(extraction_id, status="done", outcome="unknown", result=result, at=self.clock())
            return answer_of(await self._row(who.tenant_id, extraction_id))

    async def get(self, who: Who, extraction_id: str) -> Json | None:
        row = await self.store.get(extraction_id)
        if row is None or row.team != who.team:
            return None
        corrections: JsonList = [
            {
                "field": k.field,
                "record": k.record,
                "original": k.original,
                "originalConfidence": k.original_confidence,
                "corrected": k.corrected,
                "correctedBy": k.corrected_by,
                "correctedAt": k.corrected_at.isoformat(),
            }
            for k in await self.store.corrections(extraction_id)
        ]
        out = answer_of(row)
        out["corrections"] = corrections
        return out

    async def for_file(self, who: Who, file_id: str, params: ListParams) -> ListPage:
        """One page of the team's extractions of a file it can see, newest first (the file page's Fields tab)."""
        await self.files.readable(who, file_id)
        rows, page = await self.store.for_file(who.team, file_id, params)
        page["data"] = [answer_of(r) for r in rows]
        return page

    async def correct(
        self, who: Who, extraction_id: str, key: str, value: JsonValue, *, record: int | None = None
    ) -> Json | None:
        """A checker's value for one field of a done extraction. The answer then carries the corrected value, and the
        correction row keeps the original value and confidence, so a correction never erases what was extracted."""
        row = await self.store.get(extraction_id)
        if row is None or row.team != who.team:
            return None
        if row.status != "done" or row.result is None:
            raise StateError(f"{extraction_id} is {row.status}; only a done extraction is corrected")
        answer = row.result
        many = "records" in answer
        if many != (record is not None):
            raise InvalidRequestError("record names the record to correct, for an extraction of several records only")
        # Each read is the stored object itself, so the changes below land in the answer that is saved.
        records = a_list(answer["records"], "records") if many else []
        if many:
            if record is None or record >= len(records):
                raise InvalidRequestError(f"there is no record {record}")
            target = an_object(records[record], f"record {record}")
        else:
            target = answer
        fields = an_object(target["fields"], "fields")
        if key not in fields:
            raise InvalidRequestError(f"there is no field {key}")
        original = an_object(fields[key], f"field {key}")
        fields[key] = {**original, "value": value, "corrected": True, "needsReview": False}
        # A person set the value, so it no longer waits for one: the to-check count follows the correction.
        target["needsReview"] = [k for k in a_list(target.get("needsReview") or [], "needsReview") if k != key]
        if many:
            an_object(target["values"], "values")[key] = value
            answer["needsReview"] = [i for i, r in enumerate(records) if an_object(r, f"record {i}")["needsReview"]]
        await self.store.correct(
            {
                "tenant_id": who.tenant_id,
                "extraction_id": extraction_id,
                "field": key,
                "record": record,
                "original": original.get("value"),
                "original_confidence": _confidence(original),
                "corrected": value,
                "corrected_by": who.actor,
                "corrected_at": self.clock(),
            },
            answer,
            event=await self._corrected_event(who, row, answer, key, record),
            example=self._example(who, row, key, original, value, record=record),
        )
        return await self.get(who, extraction_id)

    def _example(
        self, who: Who, row: ExtractionRow, key: str, original: Json, value: JsonValue, *, record: int | None
    ) -> NewExample | None:
        """What a correction of a typed read teaches its type: the field, the line its value was printed on
        (the read's quote for it) and the corrected value, for the read's tenant and team. A read with fields of its
        own and no type teaches nothing, and neither does a correction whose quote does not show the corrected value:
        a wrong read often cites the wrong line (a banner every document carries), and that line paired with the right
        value would teach every later document of the type to read it."""
        doc_type = row.request.get("documentType")
        if not doc_type:
            return None
        citation = an_object(original.get("citation") or {}, f"field {key}'s citation")
        quote = citation.get("quote")
        if quote and value is not None and not isinstance(quote, str):
            # in_quote reads the quote as text: one that is not fails the correction, as it always has.
            raise TypeError(f"field {key}'s quote {quote!r} is not text")
        unknown: FieldDefinition = {"key": key}
        asked = next((f for f in fields_of(row.request) if f["key"] == key), unknown)
        if not in_quote(asked, value, quote if isinstance(quote, str) else None):
            return None
        return {
            "tenant_id": who.tenant_id,
            "id": f"ex_{uuid.uuid4().hex[:16]}",
            "team": row.team,
            "type_id": str(an_object(doc_type, "documentType")["id"]),
            "field": key,
            "line": citation.get("quote") or None,
            "value": value,
            "extraction_id": row.id,
            "record": SINGLE if record is None else record,
            "corrected_by": who.actor,
            "created_at": self.clock(),
        }

    async def _examples(self, row: ExtractionRow, fields: list[FieldDefinition]) -> list[Json]:
        """The recent examples of the read's type for the fields it asks; none for a read with no type."""
        doc_type = row.request.get("documentType")
        if not doc_type or self.types is None:
            return []
        keys = [f["key"] for f in fields]
        type_id = str(an_object(doc_type, "documentType")["id"])
        return await self.types.examples(row.tenant_id, row.team, type_id, keys)

    async def masks(self, who: Who) -> bool:
        """Whether the caller's team sees personal data masked."""
        return True if self.masking is None else await self.masking.masks(who.tenant_id, who.team)

    async def _corrected_event(
        self, who: Who, row: ExtractionRow, answer: Json, key: str, record: int | None
    ) -> CorrectedEvent | None:
        """extraction.corrected, so the file's saved read follows the correction (its event workflow re-runs Save data
        on file). Only for a read of a document type, and only the file's newest one for the team: correcting an
        older read must not put it back on the file over a newer one."""
        doc_type = row.request.get("documentType")
        if not doc_type:
            return None
        newest, _ = await self.store.for_file(who.team, row.file_id, ListParams(page_size=1))
        if not newest or newest[0].id != row.id:
            return None
        doc_type = an_object(doc_type, "documentType")
        name = await self.types.name(who, str(doc_type.get("id"))) if self.types is not None else None
        payload = file_read(row.file_id, row.id, doc_type, answer, name=name) | {"field": key, "record": record}
        return {
            "tenant_id": who.tenant_id,
            "team_id": who.team,
            "name": CORRECTED_EVENT,
            "key": f"{row.id}:{uuid.uuid4().hex[:12]}",
            "payload": payload,
            "actor": who.actor,
        }

    async def resume(self) -> int:
        """Starts every queued or running extraction again, after a restart; the number started."""
        pending = await self.store.pending()
        for row in pending:
            await self._later(row)
        return len(pending)

    async def drain(self) -> None:
        """Waits until no extraction is running in this process (tests and shutdown)."""
        await self._pending.none()

    async def _later(self, row: ExtractionRow) -> None:
        # Counted before the start, as the task may finish first; uncounted when it never starts, or drain would wait
        # on it forever.
        self._pending.add()
        try:
            await background.start(self._background(row), key=READING_PROCESS)
        except BaseException:
            self._pending.done()
            raise

    async def _background(self, row: ExtractionRow) -> None:
        """The read as the extraction's own tenant and team: a restart picks reads up with no request behind them. It
        runs on the supervisor, which counts each finished read and shows a failure on /health/background."""
        try:
            with isolation.scope(row.tenant_id, row.team):
                await self._read(row)
        finally:
            self._pending.done()

    async def _read(self, row: ExtractionRow) -> None:
        try:
            who = Who(tenant_id=row.tenant_id, team=row.team, actor=row.asked_by)
            file = await self.files.readable(who, row.file_id)
            await self._run(row, file, await self._pages(who, file, row.request))
        except Exception as e:
            log.warning("extraction failed", extra={"extraction": row.id, "error": str(e)})
            await self.store.finish(row.id, status="failed", at=self.clock(), error_code="failed", error=str(e))

    async def _pages(self, who: Who, file: FileInfo, request: Json) -> Pages:
        """The text the model reads, from the file's reading: titles, headings and each table cell on lines of their
        own, and each OCR'd word's confidence."""
        return page_text(layout_of(await self._reading(who, file, request)))

    async def _reading(self, who: Who, file: FileInfo, request: Json) -> Reading:
        settings = settings_of(bool(request.get("ocr")))
        if self.readings is not None:
            return await self.readings.of(who, file, settings)
        data = await self.files.read(who, file)
        return await asyncio.to_thread(read, data, filename=file.name, mime_type=file.mime, settings=settings)

    async def _run(self, row: ExtractionRow, file: FileInfo, pages: Pages) -> ExtractionRow:
        tenant, eid = row.tenant_id, row.id
        # Gate: the row marked running and committed before anything is asked, so a read cut off part-way shows it
        # ran. Each settle below saves the answer and reads it back in one transaction, after the last outside call.
        async with isolation.request_transaction():
            if not await self.store.start(eid, self.clock()):
                return await self._row(tenant, eid)
        request = row.request
        fields = fields_of(request)
        read = str(request.get("read") or "fields")
        pages, limited = _limited(pages, request)
        if not pages.texts:
            # No text layer and no OCR asked (or OCR found nothing): empty fields would pass as found.
            async with isolation.request_transaction():
                await self.store.finish(
                    eid, status="unreadable", outcome="unreadable", at=self.clock(),
                    result={"fileId": row.file_id, "pages": pages.count},
                )  # fmt: skip
                return await self._row(tenant, eid)
        many = bool(request["many"])
        pictures = self._pictures(row, file)
        layouts = entries(request.get("templates"))
        miss: Json | None = None
        if layouts and not many and pages.layout is not None:
            read, miss = await self._by_template(row, layouts, pages, pictures)
            if read is not None:
                return read
        if self.models is None:
            return await self._fail(row, "not_configured", "documents-service has no models-service key")
        usage = Usage()
        proposal: Json | None = None
        if read == "propose":
            try:
                proposal = await self._propose(row, pages, usage)
            except ModelCallError as e:
                return await self._refused(row, e, usage)
            fields = [FIELD(f) for f in entries(proposal["fields"])]
            if not fields:
                out: Json = {
                    "fileId": row.file_id, "proposal": proposal, "fields": {}, "needsReview": [], **limited,
                }  # fmt: skip
                _recorded(out, usage)
                tokens = (usage.input_tokens, usage.output_tokens)
                async with isolation.request_transaction():
                    await self.store.finish(
                        eid, status="done", outcome="ok", result=out, at=self.clock(), tokens=tokens
                    )
                    return await self._row(tenant, eid)
        schema = prompt.schema_for(fields, many=many)
        user = prompt.user_prompt(fields, pages.texts, many=many, examples=await self._examples(row, fields))
        try:
            # A page read through OCR goes with its image when the read may show it; a text page never does.
            shown = await pictures.whole(sorted(pages.ocr)) if pictures is not None else []
            answer = await self.models.structured(
                prompt.SYSTEM, user, schema, run=eid, step="extract", tenant=tenant, usage=usage, images=shown
            )
            if errors := prompt.schema_errors(answer, schema):
                again = prompt.reask(user, errors)
                answer = await self.models.structured(
                    prompt.SYSTEM, again, schema, run=eid, step="extract:reask", tenant=tenant, usage=usage,
                    images=shown,
                )  # fmt: skip
                if errors := prompt.schema_errors(answer, schema):
                    return await self._fail(
                        row, "schema_error", "The answer did not match the fields asked for.", {"details": [*errors]},
                        usage=usage,
                    )  # fmt: skip
            # With no platform-service configured the catalogue's default applies; a configured one that cannot be
            # read fails the extraction (FloorUnreadError), so a failed read never lowers the bar.
            floor = await self.floors.floor(tenant, row.team) if self.floors is not None else DEFAULT_FLOOR
        except FloorUnreadError as e:
            return await self._fail(row, "floor_unread", str(e))
        except ModelCallError as e:
            return await self._refused(row, e, usage)
        outcome, out = result.scored(
            fields,
            answer,
            pages.texts,
            pages.ocr,
            file_id=row.file_id,
            many=many,
            review_below=review_below(request),
            floor=floor,
            word_confidence=pages.confidence,
        )
        if not many:
            outcome, out = await self._ruled(row, out, pages, usage, floor, pictures=pictures)
        if pages.layout is not None:
            out = boxes.with_boxes(out, pages.layout)
        out["path"] = PATH_MODEL
        _recorded(out, usage)
        out |= limited
        if proposal is not None:
            out["proposal"] = proposal
        if miss is not None:
            out["templateMiss"] = miss
        tokens = (usage.input_tokens, usage.output_tokens)
        fp = fingerprint_of(out, pages.layout) if not many and pages.layout is not None else None
        async with isolation.request_transaction():
            await self.store.finish(
                eid, status="done", outcome=outcome, result=out, at=self.clock(), tokens=tokens, fingerprint=fp
            )
            return await self._row(tenant, eid)

    async def _by_template(
        self, row: ExtractionRow, layouts: list[JsonValue], pages: Pages, pictures: Pictures | None
    ) -> tuple[ExtractionRow | None, Json | None]:
        """The read from the first template the file matches, with no model call, or None and the best miss.
        A matched template whose required zone reads nothing is a miss too (likely the wrong form), so the model reads
        the file rather than a part being saved; a zone that reads an invalid value is re-read alone."""
        assert pages.layout is not None
        fields = fields_of(row.request)
        floor = await self.floors.floor(row.tenant_id, row.team) if self.floors is not None else DEFAULT_FLOOR
        best: templates.Miss | None = None
        for held in layouts:
            # Read when it is tried, so a template the file never reaches cannot fail the read.
            template = TEMPLATE(held)
            found = templates.match(template, pages.layout)
            if isinstance(found, templates.Miss):
                best = found if best is None or found.score > best.score else best
                continue
            outcome, out = result.scored(
                fields,
                templates.read(template, found, pages.layout),
                pages.texts,
                pages.ocr,
                file_id=row.file_id,
                many=False,
                review_below=review_below(row.request),
                floor=floor,
                word_confidence=pages.confidence,
            )
            empty = [
                f["key"]
                for f in fields
                if f.get("required")
                and an_object(an_object(out["fields"], "fields")[f["key"]], f["key"]).get("extractedValue") is None
            ]
            if empty:
                best = templates.Miss(found.template_id, 1.0, [f"zone {k} read nothing" for k in empty])
                continue
            usage = Usage()
            outcome, out = await self._ruled(row, out, pages, usage, floor, pictures=pictures)
            out = boxes.with_boxes(out, pages.layout) | {"path": PATH_TEMPLATE, "templateId": found.template_id}
            _recorded(out, usage)
            if usage.input_tokens or usage.output_tokens:
                # A field re-read by the model spent tokens; they are on the read, but kept out of the columns the test
                # estimate averages, which price a whole model read.
                out["rereadTokens"] = {"input": usage.input_tokens, "output": usage.output_tokens}
            # No tokens: a template read is left out of the measured cost an estimate prices model reads at.
            async with isolation.request_transaction():
                await self.store.finish(row.id, status="done", outcome=outcome, result=out, at=self.clock())
                return await self._row(row.tenant_id, row.id), None
        return None, best.wire() if best is not None else None

    async def _ruled(
        self,
        row: ExtractionRow,
        out: Json,
        pages: Pages,
        usage: Usage,
        floor: float,
        *,
        pictures: Pictures | None = None,
    ) -> tuple[result.Status, Json]:
        """The read after its checks: every field a rule rejected (its type, pattern, emptyWhen or a check
        across fields) is asked again in one model call naming only those fields and why; a value that now passes
        every rule replaces the first, and one that still fails goes to review with the rule named. When the read may
        show page images, a field read below its review threshold joins the re-read too, and each field
        whose words were found goes with a crop of the page around them."""
        checks = [CHECK(c) for c in entries(row.request.get("checks"))]
        fields = an_object(out["fields"], "fields")
        first = copy.deepcopy(fields)
        rules.apply(first, checks)
        failures = rules.failed(first)
        crops = await self._crops(row, first, failures, pages, floor=floor, pictures=pictures)
        failures |= {
            k: (an_object(first[k], f"field {k}").get("extractedValue"), LOW_CONFIDENCE)
            for k in crops
            if k not in failures
        }
        if failures and self.models is not None:
            asked = [f for f in fields_of(row.request) if f["key"] in failures]
            schema = prompt.schema_for(asked, many=False)
            try:
                answer = await self.models.structured(
                    prompt.SYSTEM, prompt.reread(asked, pages.texts, failures, await self._examples(row, asked)),
                    schema,
                    run=row.id, step="extract:reread", tenant=row.tenant_id, usage=usage,
                    images=list(crops.values()),
                )  # fmt: skip
            except ModelCallError:
                answer = None
            # A re-read the model cannot answer keeps the first read's values and their rule failures; an answer
            # that is not an object fails the read.
            said: Json = {k: v for k, v in an_object(answer or {}, "the re-read's answer").items() if k in failures}
            if answer is not None and not prompt.schema_errors(said, schema):
                _, again = result.scored(
                    asked, said, pages.texts, pages.ocr, file_id=row.file_id, many=False,
                    review_below=review_below(row.request), floor=floor, word_confidence=pages.confidence,
                )  # fmt: skip
                for key, value in an_object(again["fields"], "fields").items():
                    r = an_object(value, f"field {key}")
                    if not r.get("rejected") and r.get("value") is not None:
                        fields[key] = {**r, "reread": True}
        rules.apply(fields, checks)
        out["needsReview"] = [k for k, r in fields.items() if an_object(r, f"field {k}").get("needsReview")]
        return ("review" if out["needsReview"] else "ok"), out

    async def _crops(
        self,
        row: ExtractionRow,
        fields: Json,
        failures: dict[str, tuple[JsonValue, str]],
        pages: Pages,
        *,
        floor: float,
        pictures: Pictures | None,
    ) -> dict[str, page_images.PageImage]:
        """The crops a re-read shows: each field that failed a rule or was read below its threshold, where its
        words were found on the page. A doubtful field with no words found adds nothing an image could show."""
        if pictures is None or pages.layout is None or self.models is None:
            return {}
        asked = {f["key"]: f for f in fields_of(row.request)}
        below = review_below(row.request)
        doubtful: list[str] = []
        for k, value in fields.items():
            r = an_object(value, f"field {k}")
            confidence = r.get("confidence")
            if k in failures:
                doubtful.append(k)
            elif r.get("value") is not None and confidence is not None and k in asked:
                if not isinstance(confidence, int | float | str):
                    raise Malformed(f"field {k}'s confidence {confidence!r} is not a number")
                if float(confidence) < threshold(asked[k], below, floor):
                    doubtful.append(k)
        boxed: dict[str, list[Box]] = {}
        for k in doubtful:
            r = an_object(fields[k], f"field {k}")
            citation = an_object(r.get("citation") or {}, f"field {k}'s citation")
            found = boxes.locate(pages.layout, citation.get("page"), citation.get("quote"), boxes.printed(r))
            if found and found["boxes"]:
                boxed[k] = found["boxes"]
        return await pictures.crops(boxed)

    def _pictures(self, row: ExtractionRow, file: FileInfo) -> Pictures | None:
        """The read's page images when its document type version allows them, still under the team's policy,
        read on first use, and the alias, which models-service checks."""
        if not row.request.get("pageImages") or self.page_image_policy is None:
            return None
        policy = self.page_image_policy
        who = Who(tenant_id=row.tenant_id, team=row.team, actor=row.asked_by)

        async def load() -> bytes:
            return await self.files.read(who, file)

        async def allow() -> bool:
            return await policy.allowed(row.tenant_id, row.team)

        return Pictures(load, file.mime, allow)

    async def layout_of(self, who: Who, row: ExtractionRow) -> Layout:
        """The layout an extraction read: from the stored reading of its file's bytes, else read again from the file."""
        if self.readings is not None and row.file_digest:
            ocr = settings_of(bool(row.request.get("ocr")))
            stored = await self.readings.stored_of(row.team, row.file_digest, ocr)
            if stored is not None:
                return layout_of(stored)
        return layout_of(await self._reading(who, await self.files.readable(who, row.file_id), row.request))

    async def _propose(self, row: ExtractionRow, pages: Pages, usage: Usage) -> Json:
        """Fields in the document type's shape and a suggested name, read from the first pages only, so an unknown
        document's cost is bounded; the read that follows uses every page like any other. A proposed field the scorer
        could not check (no key, an unknown type, a key twice) is left out."""
        assert self.models is not None
        size = row.request.get("proposePages") or PROPOSE_PAGES
        if not isinstance(size, int | float | str):
            raise Malformed(f"proposePages {size!r} is not a number")
        first = sorted(pages.texts)[: int(size)]
        user = prompt.propose_prompt([pages.texts[n] for n in first], hint=narrow.field(row.request, "hint", str))
        answer = await self.models.structured(
            prompt.PROPOSE_SYSTEM, user, prompt.PROPOSAL_SCHEMA, run=row.id, step="propose", tenant=row.tenant_id,
            usage=usage,
        )  # fmt: skip
        raw = narrow.json_object(answer)
        kept: list[Json] = []
        for f in entries(raw.get("fields")):
            if not isinstance(f, dict):
                continue
            key, kind = f.get("key"), f.get("type") or "text"
            if not isinstance(key, str) or not key or kind not in FIELD_TYPES or any(k["key"] == key for k in kept):
                continue
            named: Json = {k: f[k] for k in ("key", "label", "description", "options") if k in f}
            kept.append(named | {"type": kind})
        return {"name": str(raw.get("name") or ""), "fields": [*kept]}

    async def _refused(self, row: ExtractionRow, e: ModelCallError, usage: Usage | None = None) -> ExtractionRow:
        code, message = REFUSALS.get(e.code or "", ("model_unavailable", str(e)))
        if e.refusal:
            message = f"{message} It said: {e.refusal}"
        return await self._fail(row, code, message, usage=usage)

    async def _fail(
        self, row: ExtractionRow, code: str, message: str, extra: Json | None = None, *, usage: Usage | None = None
    ) -> ExtractionRow:
        """Settle as failed: the error, and the tokens billed before it when there were any, saved and the row read
        back in one transaction."""
        tokens = (usage.input_tokens, usage.output_tokens) if usage is not None and usage.calls else None
        async with isolation.request_transaction():
            await self.store.finish(
                row.id, status="failed", at=self.clock(), error_code=code, error=message, result=extra, tokens=tokens
            )
            return await self._row(row.tenant_id, row.id)

    async def _row(self, tenant: str, extraction_id: str) -> ExtractionRow:
        found = await self.store.get(extraction_id)
        assert found is not None
        return found


def _limited(pages: Pages, request: Json) -> tuple[Pages, Json]:
    """The pages a read may send: the first `maxPages`, then as many as fit under `maxTokens` (ops_contracts.readings,
    which a workflow's Full text trims with too). `readPages` when a limit applied, `partial` when the token ceiling
    left pages unread."""
    max_pages = _whole(request["maxPages"], "maxPages") if request.get("maxPages") else None
    max_tokens = _whole(request["maxTokens"], "maxTokens") if request.get("maxTokens") else None
    keep, said = readings_contract.within(list(pages.texts.items()), max_pages, max_tokens)
    if not said:
        return pages, {}
    texts = {n: pages.texts[n] for n in keep}
    confidence = {n: c for n, c in pages.confidence.items() if n in texts}
    return replace(pages, texts=texts, ocr={n for n in pages.ocr if n in texts}, confidence=confidence), dict(said)


def default_extractor(files: Files, engine: Any, settings: Settings, *, readings: Readings | None = None) -> Extractor:
    """On models-service with this process's own model key (OPS_MODELS_KEY) and on platform-service for the floor.
    Without models-service every extraction fails `not_configured` rather than calling a provider; without
    platform-service the catalogue's default floor applies, as it does for the workflow worker."""
    models: Models | None = None
    if settings.models is not None and settings.models_key is not None:
        # Called with this service's model key, not a service token, so it is not a ServiceClient.
        http = httpx.AsyncClient(base_url=settings.models.base, timeout=settings.models.timeout_s)
        models = ModelsService(
            http, settings.models_key.get_secret_value(), output_tokens=settings.extract_output_tokens
        )
    floors: Floors | None = None
    pictures: PageImagePolicy | None = None
    masking: MaskingPolicy | None = None
    if (endpoint := settings.platform) is not None:
        # One HTTP client for every team's ServiceClient below; each names its own tenant and team.
        platform = httpx.AsyncClient(base_url=endpoint.base, timeout=endpoint.timeout_s)

        def client(tenant: str, team: str) -> ServiceClient:
            return ServiceClient.for_settings(
                settings,
                platform,
                service="documents",
                audience="platform",
                scopes=["settings:view"],
                timeout=endpoint.timeout_s,
                tenant=lambda: tenant,
                team=lambda: team,
            )

        try:
            client("", "")
            floors = PlatformFloors(client)
            pictures = PlatformPageImages(client)
            masking = PlatformMasking(client)
        except ValueError as e:  # no service signing key outside dev
            log.warning("no service signing key; extractions cannot read the floor", extra={"error": str(e)})
    return Extractor(
        files, ExtractionsStore(engine), models, floors, readings=readings, page_image_policy=pictures, masking=masking
    )
