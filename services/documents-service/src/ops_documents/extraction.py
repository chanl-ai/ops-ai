# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Extraction (c-235, moved to documents-service in c-256): a clean file and a schema in, every field back with its
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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from typing import Any, Protocol, cast

import httpx
import regex

from ops_access import team_off, team_on
from ops_contracts.field_values import FIELD_TYPES
from ops_documents.errors import IdempotencyConflictError, InvalidRequestError, StateError
from ops_documents.files import Files, Who
from ops_documents.layouts import Layouts
from ops_documents.store import ExtractionRow, ExtractionsStore
from ops_documents.store.document_types import SINGLE
from ops_extract import boxes, classify, page_images, prompt, result, rules, templates
from ops_extract.checks import CLEAN_RULES, DEFAULT_FLOOR, in_quote, threshold
from ops_extract.floor import FloorUnreadError, PlatformFloor
from ops_extract.layout import ENGINE as LAYOUT_ENGINE
from ops_extract.layout import page_text
from ops_extract.pages import Pages
from ops_files_client import FileInfo
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_service_kit.logging import get_logger
from ops_service_kit.settings import Settings
from ops_store import background, isolation

log = get_logger("ops_documents.extraction")

SYNC_PAGES = 5
SYNC_BYTES = 5 * 1024 * 1024
ALIAS = "extract"
FALLBACK_ALIAS = "default"


class ModelRefusedError(RuntimeError):
    """models-service refused the call or could not be reached."""


@dataclass
class Usage:
    """The model's tokens over an extraction's calls (the first ask and any re-ask), as models-service reports them."""

    input_tokens: int = 0
    output_tokens: int = 0
    # Every call that carried a page image (c-295): {step, pages, images, alias}, kept on the read.
    image_calls: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    # Why an image was not sent though the read allowed it: the alias is not cleared for images.
    image_refused: str | None = None


class Models(Protocol):
    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Usage | None = None,
        images: Sequence[page_images.PageImage] = (),
    ) -> Any: ...


class Floors(Protocol):
    async def floor(self, tenant: str, team: str) -> float: ...


class PageImagePolicy(Protocol):
    async def allowed(self, tenant: str, team: str) -> bool:
        """Whether the team's pageImages policy lets its reads show the model page images (c-295)."""
        ...


# How a read was made: from a layout template's zones (c-253) or by the model.
PATH_TEMPLATE = "template"
PATH_MODEL = "model"

# Reported when a person corrects a field (documents-service owns extraction.* events).
CORRECTED_EVENT = "extraction.corrected"


class TypeResolver(Protocol):
    async def resolve(self, who: Who, type_id: str, version: int | None) -> dict[str, Any]:
        """{id, name, version, fields, many, reviewBelow} of a team's document type version (c-236)."""
        ...

    async def list(self, who: Who) -> list[dict[str, Any]]:
        """The team's document types: {id, name, description, latestVersion} (c-249 classifies over them)."""
        ...

    async def name(self, who: Who, type_id: str) -> str | None:
        """One of the team's document types' name, or None when the team has no such type."""
        ...

    async def examples(self, tenant: str, team: str, type_id: str, keys: list[str]) -> list[dict[str, Any]]:
        """The type's recent examples for the fields a read asks (c-297): field, printed line and value."""
        ...


@dataclass
class ModelsService:
    """models-service's OpenAI-compatible completions, on documents-service's own model key (`purpose:extract`, with its
    own budget), so this service holds no provider key. The answer is the `final_result` tool's arguments, the form
    the agent kernel asks structured output in. `extract` falls back to `default` while models-service has no such
    alias (404 alias_not_found), as memory-extract does."""

    http: httpx.AsyncClient
    key: str
    alias: str = ALIAS

    async def structured(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        run: str,
        step: str,
        tenant: str,
        usage: Usage | None = None,
        images: Sequence[page_images.PageImage] = (),
    ) -> Any:
        for name in dict.fromkeys((self.alias, FALLBACK_ALIAS)):
            r = await self._post(system, user, schema, name=name, run=run, step=step, tenant=tenant, images=images)
            if images and r.status_code == 403 and "images_not_cleared" in r.text:
                # The alias may not receive page images: the read goes on with the text alone, and says why (c-295).
                if usage is not None:
                    usage.image_refused = f"The model alias {name} is not cleared for page images."
                images = ()
                r = await self._post(system, user, schema, name=name, run=run, step=step, tenant=tenant, images=images)
            if r.status_code == 404 and "alias_not_found" in r.text and name != FALLBACK_ALIAS:
                continue
            if r.status_code >= 400:
                raise ModelRefusedError(f"models-service answered {r.status_code}: {r.text[:300]}")
            body = cast(dict[str, Any], r.json())
            if usage is not None:
                counted = cast(dict[str, Any], body.get("usage") or {})
                usage.input_tokens += int(counted.get("prompt_tokens") or 0)
                usage.output_tokens += int(counted.get("completion_tokens") or 0)
                if images:
                    pages = sorted({i.page for i in images})
                    usage.image_calls.append({"step": step, "pages": pages, "images": len(images), "alias": name})
            message = cast(dict[str, Any], body["choices"][0]["message"])
            calls = cast(list[dict[str, Any]], message.get("tool_calls") or [])
            raw = calls[0]["function"]["arguments"] if calls else message.get("content")
            try:
                return json.loads(raw) if isinstance(raw, str) else {}
            except json.JSONDecodeError:
                return {}  # an unreadable answer fails the schema check and is asked again
        raise ModelRefusedError(f"models-service has neither {self.alias} nor {FALLBACK_ALIAS}")

    async def _post(
        self,
        system: str,
        user: str,
        schema: dict[str, Any],
        *,
        name: str,
        run: str,
        step: str,
        tenant: str,
        images: Sequence[page_images.PageImage],
    ) -> httpx.Response:
        content: Any = [{"type": "text", "text": user}, *(i.part() for i in images)] if images else user
        try:
            return await self.http.post(
                "/v1/models/chat/completions",
                # The tenant spends from its own share of this key, so one tenant cannot drain the others (c-251).
                headers={
                    "Authorization": f"Bearer {self.key}",
                    "X-Run-Id": run,
                    "X-Step-Id": step,
                    "X-Tenant-Id": tenant,
                },
                json={
                    "model": name,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
                    "tools": [{"type": "function", "function": {"name": "final_result", "parameters": schema}}],
                    "tool_choice": "required",
                },
            )
        except httpx.HTTPError as e:
            raise ModelRefusedError(f"models-service could not be reached: {e}") from e


@dataclass
class PlatformFloors:
    """The workspace floor (platform-service's extractionFloor policy), read per extraction with this service's token
    for the extraction's tenant and team; an unreadable floor raises FloorUnreadError (ops_extract.floor)."""

    client: Callable[[str, str], ServiceClient]

    async def floor(self, tenant: str, team: str) -> float:
        return await PlatformFloor(self.client(tenant, team)).extraction_floor()


PAGE_IMAGES_POLICY = "pageImages"
# The team's switch for personal data in what people see from AI, which covers document examples too (c-297).
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
        return not team_off(cast(dict[str, Any], found or {}).get("value"), team)


@dataclass
class PlatformPageImages:
    """The team's pageImages policy, read live from platform-service on each read that could send an image (c-295). A
    policy that cannot be read counts as off: a failed read must never send a page."""

    client: Callable[[str, str], ServiceClient]

    async def allowed(self, tenant: str, team: str) -> bool:
        try:
            found = await self.client(tenant, team).get(f"/v1/policies/{PAGE_IMAGES_POLICY}")
        except (ServiceCallError, ServiceUnreachable) as e:
            log.warning("pageImages policy unread; no page image is sent", extra={"tenant": tenant, "error": str(e)})
            return False
        return team_on(cast(dict[str, Any], found or {}).get("value"), team)


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

    async def crops(self, boxed: dict[str, list[dict[str, Any]]]) -> dict[str, page_images.PageImage]:
        """Per field, the part of its page around its boxes, or none when the policy says no."""
        if not boxed or not await self.allowed():
            return {}
        out: dict[str, page_images.PageImage] = {}
        for key, found in boxed.items():
            page = int(found[0]["page"])
            if (image := await self._page(page)) is not None:
                out[key] = page_images.crop(page, image, [b for b in found if int(b["page"]) == page])
        return out


# Why a field read below its threshold is read again with its crop (c-295), as a re-read is told.
LOW_CONFIDENCE = "was read with too little confidence to trust"


def fingerprint_of(out: dict[str, Any], layout: dict[str, Any]) -> str:
    """A single-record read's layout without its values, from the boxes its fields were found in (c-254)."""
    fields = cast(dict[str, dict[str, Any]], out.get("fields") or {})
    found = {k: cast(list[dict[str, Any]], f.get("boxes") or []) for k, f in fields.items()}
    return templates.fingerprint(templates.Read(layout, found))


def _recorded(out: dict[str, Any], usage: Usage) -> None:
    """Every call that carried a page image, and why one was not sent, on the read (c-295)."""
    if usage.image_calls:
        out["imageCalls"] = usage.image_calls
    if usage.image_refused:
        out["imageRefused"] = usage.image_refused


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _check_rules(field: dict[str, Any]) -> None:
    """A field's own rules (c-247, c-287) are refused when saved, not when a value meets them: a pattern that does not
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


def request_of(body: dict[str, Any]) -> dict[str, Any]:
    """The extraction asked for, checked: fields with a key and a known type, and the options that change the answer."""
    fields = body.get("fields")
    if not isinstance(fields, list) or not fields:
        raise InvalidRequestError("fields is a list of at least one field")
    keys: set[str] = set()
    for f in cast(list[Any], fields):
        if not isinstance(f, dict) or not isinstance(cast(dict[str, Any], f).get("key"), str):
            raise InvalidRequestError("every field has a key")
        one = cast(dict[str, Any], f)
        if (one.get("type") or "text") not in FIELD_TYPES:
            raise InvalidRequestError(
                f"field {one['key']} has type {one.get('type')!r}; types are {', '.join(FIELD_TYPES)}"
            )
        if one["key"] in keys:
            raise InvalidRequestError(f"field {one['key']} is named twice")
        keys.add(one["key"])
        _check_rules(one)
    below = body.get("reviewBelow")
    if below is not None and (isinstance(below, bool) or not isinstance(below, int | float) or not 0 <= below <= 1):
        raise InvalidRequestError("reviewBelow is a confidence between 0 and 1")
    request: dict[str, Any] = {
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
        # The type version's layout templates (c-253), tried before the model.
        request["templates"] = body["templates"]
    if body.get("checks"):
        # The type version's checks across fields (c-296), run after scoring.
        request["checks"] = body["checks"]
    if body.get("pageImages"):
        # The type version lets reads show the model page images (c-295), still under the team's policy and the alias.
        request["pageImages"] = True
    return request


def answer_of(row: ExtractionRow) -> dict[str, Any]:
    """What a caller reads: the id and status, then the scored answer once done (or what the file had when it could
    not be read), or the error once failed."""
    out: dict[str, Any] = {"id": row.id, "fileId": row.file_id, "status": row.status}
    if row.status in ("done", "unreadable") and row.result is not None:
        out |= {"outcome": row.outcome, **row.result}
    if row.status == "failed":
        out["error"] = {"code": row.error_code, "message": row.error, **(row.result or {})}
    if row.request.get("documentType"):
        out["documentType"] = row.request["documentType"]
    if row.request.get("classification"):
        out["classification"] = row.request["classification"]
    return out


@cache
def reading() -> background.Beat:
    """The document reading process's heartbeat in this process, shared by extractions and type tests."""
    return background.Beat("document_reading", background.LOCAL)


@dataclass
class Extractor:
    files: Files
    store: ExtractionsStore
    models: Models | None
    floors: Floors | None
    alias: str = ALIAS
    types: TypeResolver | None = None
    # The cached layouts extraction reads (c-247); without them each extraction reads the file's layout itself.
    layouts: Layouts | None = None
    # The team's pageImages policy (c-295); without it no read sends a page image.
    page_image_policy: PageImagePolicy | None = None
    # The team's masking of personal data in what people see (c-297); without it, masked.
    masking: MaskingPolicy | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _tasks: set[asyncio.Task[None]] = field(default_factory=set[asyncio.Task[None]])

    async def ask(
        self,
        who: Who,
        file_id: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        inline: bool = False,
    ) -> tuple[int, dict[str, Any]]:
        """(200, the answer) when it ran now or had already finished, (202, its id and status) when it runs later.
        `inline` runs it now whatever the file's size (a document type's test, already running as a task). A request
        naming `documentTypeId` reads with that type's version (the newest when `version` is not given); one asking
        `detect` classifies the file over the team's types first (c-249), and reads with the kind it found, or
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
            body = kept | {"documentTypeId": found["typeId"], "classification": found}
        if body.get("documentTypeId"):
            if self.types is None:
                raise InvalidRequestError("document types are not served here")
            t = await self.types.resolve(who, str(body["documentTypeId"]), body.get("version"))
            below = body.get("reviewBelow")
            body = {
                "fields": t["fields"],
                "many": t["many"],
                "ocr": body.get("ocr"),
                "reviewBelow": below if below is not None else t["reviewBelow"],
                # The name travels with the read, so a workflow's Extract step records it on the file (c-378).
                "documentType": {
                    "id": t["id"],
                    "version": t["version"],
                    **({"name": t["name"]} if t.get("name") else {}),
                },
                **({"classification": body["classification"]} if body.get("classification") else {}),
                **({"templates": t["templates"]} if t.get("templates") else {}),
                **({"checks": t["checks"]} if t.get("checks") else {}),
                **({"pageImages": True} if t.get("pageImages") else {}),
            }
        request = request_of(body)
        row = await self.files.readable(who, file_id)
        extraction_id = f"ext_{uuid.uuid4().hex[:16]}"
        request_hash = _sha(json.dumps({"file": file_id, **request}, sort_keys=True))
        key = idempotency_key if idempotency_key is not None else extraction_id
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
                "type_id": cast(dict[str, Any], request.get("documentType") or {}).get("id"),
                "asked_by": who.actor,
                "asked_at": self.clock(),
            }
        )
        if held.id != extraction_id:
            if held.request_hash != request_hash:
                raise IdempotencyConflictError("this Idempotency-Key was used for a different extraction")
            if held.status != "failed" or held.error_code == "schema_error":
                return (200 if held.status not in ("queued", "running") else 202), answer_of(held)
            # A retry after the floor or the model was out of reach runs it again; a schema error stays the answer.
            held = await self.store.requeue(held.id)
        pages = None
        if inline or row.size <= SYNC_BYTES:
            pages = await self._pages(who, row, request)
        if not inline and (pages is None or pages.count > SYNC_PAGES):
            self._later(held)
            return 202, answer_of(held)
        assert pages is not None  # parsed above whenever the extraction runs now
        return 200, answer_of(await self._run(held, row, pages))

    async def classify(self, who: Who, file: FileInfo, *, ocr: bool) -> dict[str, Any]:
        """Which of the team's document types the file is (c-249, the model's answer over each type's name and
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
        answer = await self.models.structured(
            classify.SYSTEM, user, schema, run=run, step="classify", tenant=who.tenant_id
        )
        if prompt.schema_errors(answer, schema):
            return classify.classification({"reason": "The model's answer named no listed type."}, types, floor)
        return classify.classification(cast(dict[str, Any], answer), types, floor)

    async def _unknown(
        self, who: Who, file: FileInfo, found: dict[str, Any], body: dict[str, Any], idempotency_key: str | None
    ) -> dict[str, Any]:
        """A detect read whose kind is unknown or doubtful: recorded done with outcome unknown and no fields, so the
        workflow sends it to a person instead of reading it with the wrong type's fields."""
        request: dict[str, Any] = {
            "fields": [],
            "many": False,
            "ocr": bool(body.get("ocr")),
            "reviewBelow": None,
            "detect": True,
            "classification": found,
        }
        extraction_id = f"ext_{uuid.uuid4().hex[:16]}"
        key = idempotency_key if idempotency_key is not None else extraction_id
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
        result = {"fileId": file.id, "fields": {}, "needsReview": ["documentType"], "classification": found}
        await self.store.finish(extraction_id, status="done", outcome="unknown", result=result, at=self.clock())
        return answer_of(await self._row(who.tenant_id, extraction_id))

    async def get(self, who: Who, extraction_id: str) -> dict[str, Any] | None:
        row = await self.store.get(extraction_id)
        if row is None or row.team != who.team:
            return None
        return answer_of(row) | {"corrections": await self.store.corrections(extraction_id)}

    async def for_file(self, who: Who, file_id: str, *, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
        """One page of the team's extractions of a file it can see, newest first (c-250: the file page's Fields tab)."""
        await self.files.readable(who, file_id)
        rows, total = await self.store.for_file(who.team, file_id, offset=(page - 1) * page_size, limit=page_size)
        return [answer_of(r) for r in rows], total

    async def correct(
        self, who: Who, extraction_id: str, key: str, value: Any, *, record: int | None = None
    ) -> dict[str, Any] | None:
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
        if many:
            records = cast(list[dict[str, Any]], answer["records"])
            if record is None or record >= len(records):
                raise InvalidRequestError(f"there is no record {record}")
            target = records[record]
        else:
            target = answer
        fields = cast(dict[str, dict[str, Any]], target["fields"])
        if key not in fields:
            raise InvalidRequestError(f"there is no field {key}")
        original = fields[key]
        fields[key] = {**original, "value": value, "corrected": True, "needsReview": False}
        # A person set the value, so it no longer waits for one: the to-check count follows the correction.
        target["needsReview"] = [k for k in cast(list[str], target.get("needsReview") or []) if k != key]
        if many:
            target["values"][key] = value
            every = cast(list[dict[str, Any]], answer["records"])
            answer["needsReview"] = [i for i, r in enumerate(every) if r["needsReview"]]
        await self.store.correct(
            {
                "tenant_id": who.tenant_id,
                "extraction_id": extraction_id,
                "field": key,
                "record": record,
                "original": original.get("value"),
                "original_confidence": float(original.get("confidence") or 0.0),
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
        self, who: Who, row: ExtractionRow, key: str, original: dict[str, Any], value: Any, *, record: int | None
    ) -> dict[str, Any] | None:
        """What a correction of a typed read teaches its type (c-297): the field, the line its value was printed on
        (the read's quote for it) and the corrected value, for the read's tenant and team. A read with fields of its
        own and no type teaches nothing, and neither does a correction whose quote does not show the corrected value:
        a wrong read often cites the wrong line (a banner every document carries), and that line paired with the right
        value would teach every later document of the type to read it."""
        doc_type = cast(dict[str, Any] | None, row.request.get("documentType"))
        if not doc_type:
            return None
        citation = cast(dict[str, Any], original.get("citation") or {})
        fields = cast(list[dict[str, Any]], row.request.get("fields") or [])
        asked = next((f for f in fields if f["key"] == key), dict[str, Any]())
        if not in_quote(asked, value, citation.get("quote")):
            return None
        return {
            "tenant_id": who.tenant_id,
            "id": f"ex_{uuid.uuid4().hex[:16]}",
            "team": row.team,
            "type_id": str(doc_type["id"]),
            "field": key,
            "line": citation.get("quote") or None,
            "value": value,
            "extraction_id": row.id,
            "record": SINGLE if record is None else record,
            "corrected_by": who.actor,
            "created_at": self.clock(),
        }

    async def _examples(self, row: ExtractionRow, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The recent examples of the read's type for the fields it asks (c-297); none for a read with no type."""
        doc_type = cast(dict[str, Any] | None, row.request.get("documentType"))
        if not doc_type or self.types is None:
            return []
        keys = [str(f["key"]) for f in fields]
        return await self.types.examples(row.tenant_id, row.team, str(doc_type["id"]), keys)

    async def masks(self, who: Who) -> bool:
        """Whether the caller's team sees personal data masked (c-297)."""
        return True if self.masking is None else await self.masking.masks(who.tenant_id, who.team)

    async def _corrected_event(
        self, who: Who, row: ExtractionRow, answer: dict[str, Any], key: str, record: int | None
    ) -> dict[str, Any] | None:
        """extraction.corrected, so the file's saved read follows the correction (its event workflow re-runs Save data
        on file). Only for a read of a document type, and only the file's newest one for the team: correcting an
        older read must not put it back on the file over a newer one."""
        doc_type = cast(dict[str, Any] | None, row.request.get("documentType"))
        if not doc_type:
            return None
        newest, _ = await self.store.for_file(who.team, row.file_id, offset=0, limit=1)
        if not newest or newest[0].id != row.id:
            return None
        name = await self.types.name(who, str(doc_type.get("id"))) if self.types is not None else None
        payload: dict[str, Any] = {
            "fileId": row.file_id,
            "extractionId": row.id,
            "documentType": doc_type,
            "needsReview": answer["needsReview"],
            "field": key,
            "record": record,
        }
        if name:
            payload["typeName"] = name
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
            self._later(row)
        return len(pending)

    async def drain(self) -> None:
        """Waits for the extractions running in this process (tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _later(self, row: ExtractionRow) -> None:
        task = asyncio.create_task(self._background(row))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _background(self, row: ExtractionRow) -> None:
        """The read as the extraction's own tenant and team: a restart picks reads up with no request behind them.
        Each finished read counts on the document reading process's heartbeat."""
        with isolation.scope(row.tenant_id, row.team):
            try:
                await self._read(row)
            except Exception as e:
                await reading().failed(e)
                raise
        await reading().ok(1, waiting=max(0, len(self._tasks) - 1))

    async def _read(self, row: ExtractionRow) -> None:
        try:
            who = Who(tenant_id=row.tenant_id, team=row.team, actor=row.asked_by)
            file = await self.files.readable(who, row.file_id)
            await self._run(row, file, await self._pages(who, file, row.request))
        except Exception as e:
            log.warning("extraction failed", extra={"extraction": row.id, "error": str(e)})
            await self.store.finish(row.id, status="failed", at=self.clock(), error_code="failed", error=str(e))

    async def _pages(self, who: Who, file: FileInfo, request: dict[str, Any]) -> Pages:
        """The text the model reads, from the file's layout: titles, headings and each table cell on lines of their
        own, and each OCR'd word's confidence (c-247)."""
        layouts = self.layouts or Layouts(self.files)
        return page_text(await layouts.of(who, file, ocr=bool(request["ocr"])))

    async def _run(self, row: ExtractionRow, file: FileInfo, pages: Pages) -> ExtractionRow:
        tenant, eid = row.tenant_id, row.id
        if not await self.store.start(eid, self.clock()):
            done = await self.store.get(eid)
            assert done is not None
            return done
        request = row.request
        fields = cast(list[dict[str, Any]], request["fields"])
        if not pages.texts:
            # No text layer and no OCR asked (or OCR found nothing): empty fields would pass as found.
            await self.store.finish(
                eid, status="unreadable", outcome="unreadable", at=self.clock(),
                result={"fileId": row.file_id, "pages": pages.count},
            )  # fmt: skip
            return await self._row(tenant, eid)
        many = bool(request["many"])
        pictures = self._pictures(row, file)
        layouts = cast(list[dict[str, Any]], request.get("templates") or [])
        miss: dict[str, Any] | None = None
        if layouts and not many and pages.layout is not None:
            read, miss = await self._by_template(row, layouts, pages, pictures)
            if read is not None:
                return read
        if self.models is None:
            await self._fail(row, "not_configured", "documents-service has no models-service key")
            return await self._row(tenant, eid)
        schema = prompt.schema_for(fields, many=many)
        user = prompt.user_prompt(fields, pages.texts, many=many, examples=await self._examples(row, fields))
        usage = Usage()
        try:
            # A page read through OCR goes with its image when the read may show it (c-295); a text page never does.
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
                    await self._fail(
                        row, "schema_error", "The answer did not match the fields asked for.", {"details": errors}
                    )
                    return await self._row(tenant, eid)
            # With no platform-service configured the catalogue's default applies; a configured one that cannot be
            # read fails the extraction (FloorUnreadError), so a failed read never lowers the bar.
            floor = await self.floors.floor(tenant, row.team) if self.floors is not None else DEFAULT_FLOOR
        except FloorUnreadError as e:
            await self._fail(row, "floor_unread", str(e))
            return await self._row(tenant, eid)
        except ModelRefusedError as e:
            await self._fail(row, "model_unavailable", str(e))
            return await self._row(tenant, eid)
        outcome, out = result.scored(
            fields,
            answer,
            pages.texts,
            pages.ocr,
            file_id=row.file_id,
            many=many,
            review_below=request.get("reviewBelow"),
            floor=floor,
            word_confidence=pages.confidence,
        )
        if not many:
            outcome, out = await self._ruled(row, out, pages, usage, floor, pictures=pictures)
        if pages.layout is not None:
            out = boxes.with_boxes(out, pages.layout)
        out["path"] = PATH_MODEL
        _recorded(out, usage)
        if miss is not None:
            out["templateMiss"] = miss
        tokens = (usage.input_tokens, usage.output_tokens)
        fp = fingerprint_of(out, pages.layout) if not many and pages.layout is not None else None
        await self.store.finish(
            eid, status="done", outcome=outcome, result=out, at=self.clock(), tokens=tokens, fingerprint=fp
        )
        return await self._row(tenant, eid)

    async def _by_template(
        self, row: ExtractionRow, layouts: list[dict[str, Any]], pages: Pages, pictures: Pictures | None
    ) -> tuple[ExtractionRow | None, dict[str, Any] | None]:
        """The read from the first template the file matches, with no model call, or None and the best miss (c-253).
        A matched template whose required zone reads nothing is a miss too (likely the wrong form), so the model reads
        the file rather than a part being saved; a zone that reads an invalid value is re-read alone (c-296)."""
        assert pages.layout is not None
        fields = cast(list[dict[str, Any]], row.request["fields"])
        floor = await self.floors.floor(row.tenant_id, row.team) if self.floors is not None else DEFAULT_FLOOR
        best: templates.Miss | None = None
        for template in layouts:
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
                review_below=row.request.get("reviewBelow"),
                floor=floor,
                word_confidence=pages.confidence,
            )
            empty = [
                str(f["key"])
                for f in fields
                if f.get("required") and out["fields"][str(f["key"])].get("extractedValue") is None
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
            await self.store.finish(row.id, status="done", outcome=outcome, result=out, at=self.clock())
            return await self._row(row.tenant_id, row.id), None
        return None, best.wire() if best is not None else None

    async def _ruled(
        self,
        row: ExtractionRow,
        out: dict[str, Any],
        pages: Pages,
        usage: Usage,
        floor: float,
        *,
        pictures: Pictures | None = None,
    ) -> tuple[result.Status, dict[str, Any]]:
        """The read after its checks (c-296): every field a rule rejected (its type, pattern, emptyWhen or a check
        across fields) is asked again in one model call naming only those fields and why; a value that now passes
        every rule replaces the first, and one that still fails goes to review with the rule named. When the read may
        show page images (c-295), a field read below its review threshold joins the re-read too, and each field
        whose words were found goes with a crop of the page around them."""
        checks = cast(list[dict[str, Any]], row.request.get("checks") or [])
        fields = cast(dict[str, dict[str, Any]], out["fields"])
        first = copy.deepcopy(fields)
        rules.apply(first, checks)
        failures = rules.failed(first)
        crops = await self._crops(row, first, failures, pages, floor=floor, pictures=pictures)
        failures |= {k: (first[k].get("extractedValue"), LOW_CONFIDENCE) for k in crops if k not in failures}
        if failures and self.models is not None:
            asked = [f for f in cast(list[dict[str, Any]], row.request["fields"]) if str(f["key"]) in failures]
            schema = prompt.schema_for(asked, many=False)
            try:
                answer = await self.models.structured(
                    prompt.SYSTEM, prompt.reread(asked, pages.texts, failures, await self._examples(row, asked)),
                    schema,
                    run=row.id, step="extract:reread", tenant=row.tenant_id, usage=usage,
                    images=list(crops.values()),
                )  # fmt: skip
            except ModelRefusedError:
                answer = None
            said = {k: v for k, v in cast(dict[str, Any], answer or {}).items() if k in failures}
            if answer is not None and not prompt.schema_errors(said, schema):
                _, again = result.scored(
                    asked, said, pages.texts, pages.ocr, file_id=row.file_id, many=False,
                    review_below=row.request.get("reviewBelow"), floor=floor, word_confidence=pages.confidence,
                )  # fmt: skip
                for key, r in cast(dict[str, dict[str, Any]], again["fields"]).items():
                    if not r.get("rejected") and r.get("value") is not None:
                        fields[key] = {**r, "reread": True}
        rules.apply(fields, checks)
        out["needsReview"] = [k for k, r in fields.items() if r.get("needsReview")]
        return ("review" if out["needsReview"] else "ok"), out

    async def _crops(
        self,
        row: ExtractionRow,
        fields: dict[str, dict[str, Any]],
        failures: dict[str, tuple[Any, str]],
        pages: Pages,
        *,
        floor: float,
        pictures: Pictures | None,
    ) -> dict[str, page_images.PageImage]:
        """The crops a re-read shows (c-295): each field that failed a rule or was read below its threshold, where its
        words were found on the page. A doubtful field with no words found adds nothing an image could show."""
        if pictures is None or pages.layout is None or self.models is None:
            return {}
        asked = {str(f["key"]): f for f in cast(list[dict[str, Any]], row.request["fields"])}
        below = row.request.get("reviewBelow")
        doubtful = [
            k
            for k, r in fields.items()
            if k in failures
            or (
                r.get("value") is not None
                and r.get("confidence") is not None
                and k in asked
                and float(r["confidence"]) < threshold(asked[k], below, floor)
            )
        ]
        boxed: dict[str, list[dict[str, Any]]] = {}
        for k in doubtful:
            citation = cast(dict[str, Any], fields[k].get("citation") or {})
            found = boxes.locate(pages.layout, citation.get("page"), citation.get("quote"), boxes.printed(fields[k]))
            if found and found.get("boxes"):
                boxed[k] = cast(list[dict[str, Any]], found["boxes"])
        return await pictures.crops(boxed)

    def _pictures(self, row: ExtractionRow, file: FileInfo) -> Pictures | None:
        """The read's page images when its document type version allows them (c-295), still under the team's policy,
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

    async def layout_of(self, who: Who, row: ExtractionRow) -> dict[str, Any]:
        """The layout an extraction read: the cached one for its file's digest, else read again from the file."""
        ocr = bool(row.request.get("ocr"))
        layouts = self.layouts or Layouts(self.files)
        if layouts.store is not None:
            cached = await layouts.store.get(row.file_digest, LAYOUT_ENGINE, ocr=ocr)
            if cached is not None:
                return cached
        return await layouts.of(who, await self.files.readable(who, row.file_id), ocr=ocr)

    async def _fail(self, row: ExtractionRow, code: str, message: str, extra: dict[str, Any] | None = None) -> None:
        await self.store.finish(row.id, status="failed", at=self.clock(), error_code=code, error=message, result=extra)

    async def _row(self, tenant: str, extraction_id: str) -> ExtractionRow:
        found = await self.store.get(extraction_id)
        assert found is not None
        return found


def default_extractor(files: Files, engine: Any, settings: Settings, *, layouts: Layouts | None = None) -> Extractor:
    """On models-service with this process's own model key (OPS_MODELS_KEY) and on platform-service for the floor.
    Without models-service every extraction fails `not_configured` rather than calling a provider; without
    platform-service the catalogue's default floor applies, as it does for the workflow worker."""
    models: Models | None = None
    if settings.models_url and settings.models_key is not None:
        http = httpx.AsyncClient(base_url=settings.models_url, timeout=120)
        models = ModelsService(http, settings.models_key.get_secret_value())
    floors: Floors | None = None
    pictures: PageImagePolicy | None = None
    masking: MaskingPolicy | None = None
    if settings.platform_url:
        platform = httpx.AsyncClient(base_url=settings.platform_url, timeout=10)

        def client(tenant: str, team: str) -> ServiceClient:
            return ServiceClient.for_settings(
                settings,
                platform,
                service="documents",
                audience="platform",
                scopes=["settings:view"],
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
        files, ExtractionsStore(engine), models, floors, layouts=layouts, page_image_policy=pictures, masking=masking
    )
