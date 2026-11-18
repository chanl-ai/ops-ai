# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Document types: a schema a team defines once, versions and tests, so workflows and agents read with one
tested set of fields instead of a copy each.

A type belongs to a team. Saving its fields makes an immutable version n+1; an extraction names the type and a version
(the newest when none) and its answer says which version it read. A sample is one of the team's files with the values
it should read, kept in Files by a `test_set` reference while the sample names it. Testing a version runs every sample
(at most `MAX_TEST_SAMPLES`) through the extraction API, as a task with its status on its row, and compares each field
with its expected value after the checks' own normalisation, so "3,250.00" read for an expected 3250 is a match. A
test spends a model call per sample, so its estimate (calls and cost from the alias's price) is offered first."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol, TypedDict, cast

from ops_contracts.field_values import DATE_ORDERS, DEFAULT_DATE_ORDER, normalise
from ops_documents.errors import CreateNotAllowedError, DocumentTypeMissingError, InvalidRequestError, StateError
from ops_documents.extraction import (
    ALIAS,
    FALLBACK_ALIAS,
    FIELD,
    PATH_TEMPLATE,
    TEMPLATE,
    Extractor,
    ResolvedVersion,
    fields_of,
    request_of,
)
from ops_documents.files import Files, Who
from ops_documents.pending import Pending
from ops_documents.readings import READING_PROCESS
from ops_documents.store.document_types import (
    SINGLE,
    DocumentTypesStore,
    ExampleRow,
    NameTakenError,
    SampleRow,
    TestRow,
    TypeRow,
    VersionOptions,
    VersionRow,
)
from ops_documents.store.extractions import ExtractionRow
from ops_extract import boxes, rules, templates
from ops_extract.checks import fold
from ops_extract.shapes import FieldDefinition
from ops_identity import ServiceCallError, ServiceClient, ServiceUnreachable
from ops_pii import mask
from ops_service_kit.http import Json, JsonList, JsonValue, PageJSON
from ops_service_kit.listing import ListParams
from ops_service_kit.logging import get_logger
from ops_service_kit.narrow import a_list, an_object, entries, json_list, json_object
from ops_service_kit.settings import Settings
from ops_store import background, isolation

log = get_logger("ops_documents.document_types")

MAX_TEST_SAMPLES = 20
# What one extraction call is assumed to spend, for the estimate before a test: a few pages in, the fields out.
TOKENS_IN_PER_CALL = 4000
TOKENS_OUT_PER_CALL = 600
_ID = re.compile(r"[a-z][a-z0-9_]{2,63}")

__all__ = ["MAX_TEST_SAMPLES", "DocumentTypes", "ModelsPrices", "NameTakenError", "Prices"]


class Prices(Protocol):
    async def price(self, alias: str, *, tenant: str) -> tuple[Decimal, Decimal] | None:
        """(input, output) price per million tokens of the alias's current version; None when unknown."""
        ...


class AliasPrice(TypedDict):
    """The fields of models-service's alias row a price reads."""

    inputPerMillion: str
    outputPerMillion: str


class AliasPage(TypedDict):
    data: list[AliasPrice]


@dataclass
class ModelsPrices:
    """An alias's price from models-service (its alias versions), for a test's estimate; `extract` falls back to
    `default` while unbound, as extractions do. None when models-service cannot say."""

    client: ServiceClient

    async def price(self, alias: str, *, tenant: str) -> tuple[Decimal, Decimal] | None:
        for name in dict.fromkeys((alias, FALLBACK_ALIAS)):
            try:
                # models-service refuses a service token that names no tenant (401), which read as "no price". The
                # alias list answers each alias's serving version, which its versions list may hold past page one.
                page = await self.client.request("GET", "/v1/models/aliases", params={"ids": name}, tenant=tenant)
            except (ServiceCallError, ServiceUnreachable):
                return None
            current = cast(AliasPage, page)["data"]
            if current:
                return Decimal(str(current[0]["inputPerMillion"])), Decimal(str(current[0]["outputPerMillion"]))
        return None


def carried(template: Json, keys: set[str]) -> Json:
    """A template carried to a new version: valid while every field its zones read is still there, else flagged. It
    is read as posted input, since the new version's `templates.problems` refuses one that is wrongly shaped."""
    read = {
        str(an_object(z, "a zone")["field"])
        for p in entries(template.get("pages"))
        for z in entries(an_object(p, "a template page").get("zones"))
    }
    kept = {k: v for k, v in template.items() if k != templates.NEEDS_REBUILD}
    return kept if read <= keys else {**kept, templates.NEEDS_REBUILD: True}


def dated(fields: list[Json], order: str | None) -> list[Json]:
    """The version's fields with its date order on each date field, so reading and scoring agree on 03/04/2026."""
    return [{**f, "dateOrder": order or DEFAULT_DATE_ORDER} if f.get("type") == "date" else f for f in fields]


class TypeSummary(TypedDict):
    """A type as the list answers it (`DocumentTypeRow`)."""

    id: str
    name: str
    description: str | None
    latestVersion: int


class TypePage(TypedDict):
    """A page of the team's types (`DocumentTypeList`)."""

    data: list[TypeSummary]
    pagination: PageJSON
    facets: dict[str, dict[str, int]]
    canCreate: bool


def _version_view(v: VersionRow) -> Json:
    return {
        "version": v.version,
        "fields": [*v.fields],
        "many": v.many,
        "reviewBelow": v.review_below,
        "dateOrder": v.date_order or DEFAULT_DATE_ORDER,
        "templates": [*(v.templates or [])],
        "checks": [*(v.checks or [])],
        "pageImages": bool(v.page_images),
        "offerAt": v.offer_at or DEFAULT_OFFER_AT,
        "note": v.note,
        "createdBy": v.created_by,
        "createdAt": v.created_at.isoformat(),
    }


def _sample_view(s: SampleRow) -> Json:
    return {
        "id": s.id,
        "fileId": s.file_id,
        "name": s.name,
        "expected": s.expected,
        "addedBy": s.added_by,
        "addedAt": s.added_at.isoformat(),
    }


def _test_view(t: TestRow) -> Json:
    out: Json = {
        "id": t.id,
        "typeId": t.type_id,
        "version": t.version,
        "status": t.status,
        "samples": t.samples,
        "askedBy": t.asked_by,
        "askedAt": t.asked_at.isoformat(),
    }
    if t.result is not None:
        out["result"] = t.result
    if t.error:
        out["error"] = t.error
    return out


def example_view(e: ExampleRow) -> Json:
    """An example as a read is given it and a person sees it: its record's position, or none for a read of one."""
    return {
        "id": e.id,
        "field": e.field,
        "line": e.line,
        "value": e.value,
        "extractionId": e.extraction_id,
        "record": None if e.record == SINGLE else e.record,
        "correctedBy": e.corrected_by,
        "createdAt": e.created_at.isoformat(),
    }


def matches(f: FieldDefinition, expected: Any, got: Any) -> bool:
    """A read value against the expected one, both normalised as the checks normalise a field (numbers, money,
    dates), and text compared folded (case, quotes, runs of space)."""
    want, _ = normalise(f, expected) if expected is not None else (None, 0.0)
    if want is None:
        want = expected
    if isinstance(want, str) and isinstance(got, str):
        return fold(want) == fold(got)
    return want == got


@dataclass
class DocumentTypes:
    store: DocumentTypesStore
    files: Files
    extractor: Extractor
    prices: Prices | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    _pending: Pending = field(default_factory=Pending)

    # ── types and versions ──

    @staticmethod
    def _may_write(who: Who, *, adding: bool = False) -> None:
        """Changing a type is documents.edit; adding one is documents.create too, which the roles grid keeps from
        viewers, who keep the team's types but add none."""
        if not who.edits or (adding and not who.creates):
            verb = "add" if adding else "change"
            raise CreateNotAllowedError(f"Your role in this team cannot {verb} document types.")

    def may_change(self, who: Who) -> None:
        """Refuses a role that cannot change the team's document types, before a route changes anything."""
        self._may_write(who)

    async def create(self, who: Who, body: dict[str, Any]) -> dict[str, Any]:
        self._may_write(who, adding=True)
        type_id = body.get("id") or f"dt_{uuid.uuid4().hex[:12]}"
        if not _ID.fullmatch(type_id) and not type_id.startswith("dt_"):
            raise InvalidRequestError("id is 3 to 64 lowercase letters, digits and underscores, starting with a letter")
        name = str(body.get("name") or "").strip()
        if not name:
            raise InvalidRequestError("a document type has a name")
        version = self._checked(body)
        self._may_show_pages(who, version, held=False)
        now = self.clock()
        await self.store.create(
            {
                "tenant_id": who.tenant_id,
                "id": type_id,
                "team": who.team,
                "name": name[:200],
                "description": body.get("description"),
                "created_by": who.actor,
                "created_at": now,
            },
            {**version, "created_by": who.actor, "created_at": now},
        )
        found = await self.get(who, type_id)
        assert found is not None
        return found

    def _checked(self, body: dict[str, Any], *, carried_forward: bool = False) -> VersionOptions:
        """The version's fields and options, checked as an extraction request checks them. Only a template this service
        carried forward may be flagged needsRebuild: a posted flag is dropped, so a posted zone naming a field the
        version lacks is refused rather than saved unchecked."""
        request = request_of(
            {"fields": body.get("fields"), "many": body.get("many"), "reviewBelow": body.get("reviewBelow")}
        )
        order = body.get("dateOrder") or DEFAULT_DATE_ORDER
        if order not in DATE_ORDERS:
            raise InvalidRequestError("dateOrder is MDY (month first) or DMY (day first)")
        offer_at = body.get("offerAt") or DEFAULT_OFFER_AT
        if isinstance(offer_at, bool) or not isinstance(offer_at, int) or offer_at < MIN_OFFER_AT:
            raise InvalidRequestError(f"offerAt is a whole number of reads, at least {MIN_OFFER_AT}")
        given: JsonValue = body.get("templates") or []
        layouts: JsonList = json_list(given)
        if not carried_forward:
            # A template that is not an object is kept as it is, so `problems` refuses it by name.
            layouts = [
                {k: v for k, v in t.items() if k != templates.NEEDS_REBUILD} if isinstance(t, dict) else t
                for t in layouts
            ]
        if layouts and request["many"]:
            raise InvalidRequestError("templates read one record; a type reading several takes the model path")
        asked = fields_of(request)
        keys = {f["key"] for f in asked}
        if found := templates.problems(layouts if isinstance(given, list) else given, keys):
            raise InvalidRequestError("; ".join(found[:5]))
        held_checks: JsonValue = body.get("checks") or []
        checks: JsonList = json_list(held_checks)
        types = {f["key"]: str(f.get("type") or "text") for f in asked}
        if found := rules.problems(held_checks, keys, types):
            raise InvalidRequestError("; ".join(found[:5]))
        return {
            "fields": a_list(request["fields"], "fields"),
            "many": bool(request["many"]),
            "review_below": request["reviewBelow"],
            "date_order": order,
            "templates": layouts,
            "checks": checks,
            "page_images": bool(body.get("pageImages")),
            "offer_at": offer_at,
            "note": body.get("note"),
        }

    @staticmethod
    def _may_show_pages(who: Who, version: VersionOptions, *, held: bool) -> None:
        """Page images leave for the model provider: turning them on needs documents.manage; a version keeping
        what the one before held, or turning them off, needs only documents.edit."""
        if version["page_images"] and not held and not who.manages:
            raise CreateNotAllowedError("Turning on page images needs someone who manages the team's documents.")

    async def add_version(self, who: Who, type_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        self._may_write(who)
        if await self._own(who, type_id) is None:
            return None
        latest = await self.resolve(who, type_id, None)
        keys = {str(an_object(f, "a field")["key"]) for f in entries(body.get("fields"))}
        carried_forward = body.get("templates") is None
        if carried_forward:
            # Templates a person saved are not lost to a new version that does not name them: each is carried forward,
            # and one reading a field the new version no longer has is flagged for a rebuild and never matched.
            saved = latest["allTemplates"]
            body = {**body, "templates": [carried(t, keys) for t in saved]}
        if body.get("checks") is None:
            # Checks carry forward too; one naming a field the new version lacks is dropped, since it cannot run.
            held = latest["checks"]
            body = {**body, "checks": [c for c in held if set(rules.named(c)) <= keys]}
        if body.get("pageImages") is None:
            body = {**body, "pageImages": latest["pageImages"]}
        if body.get("offerAt") is None:
            body = {**body, "offerAt": latest["offerAt"]}
        version = self._checked(body, carried_forward=carried_forward)
        self._may_show_pages(who, version, held=bool(latest["pageImages"]))
        n = await self.store.add_version(type_id, {**version, "created_by": who.actor, "created_at": self.clock()})
        found = await self.store.version(type_id, n)
        assert found is not None
        return _version_view(found)

    async def delete(self, who: Who, type_id: str) -> bool:
        """Deletes the team's type. Whoever keeps the team's document types (documents.edit) removes one too, so a
        member who may add a type may take it away again."""
        self._may_write(who)
        return await self.store.delete(who.team, type_id)

    async def get_version(self, who: Who, type_id: str, version: int) -> Json | None:
        if await self._own(who, type_id) is None:
            return None
        found = await self.store.version(type_id, version)
        return _version_view(found) if found is not None else None

    async def _own(self, who: Who, type_id: str) -> TypeRow | None:
        row = await self.store.get(type_id)
        return row if row is not None and row.team == who.team else None

    async def get(self, who: Who, type_id: str) -> Json | None:
        row = await self._own(who, type_id)
        if row is None:
            return None
        versions = await self.store.versions(type_id)
        samples = await self.store.samples(type_id)
        return {
            "id": row.id,
            "name": row.name,
            "description": row.description,
            "team": row.team,
            "latestVersion": row.latest_version,
            "createdBy": row.created_by,
            "createdAt": row.created_at.isoformat(),
            "versions": [_version_view(v) for v in versions],
            "samples": [_sample_view(s) for s in samples],
            "canEdit": who.edits,
        }

    async def list(self, who: Who) -> list[TypeSummary]:
        return [
            {"id": r.id, "name": r.name, "description": r.description, "latestVersion": r.latest_version}
            for r in await self.store.every(who.team)
        ]

    async def page(self, who: Who, params: ListParams) -> TypePage:
        """One page of the team's types, and whether the caller may add one (the console's New type)."""
        rows, page = await self.store.list(who.team, params)
        listed = [
            TypeSummary(id=r.id, name=r.name, description=r.description, latestVersion=r.latest_version) for r in rows
        ]
        return TypePage(data=listed, pagination=page["pagination"], facets=page["facets"], canCreate=who.creates)

    async def name(self, who: Who, type_id: str) -> str | None:
        row = await self._own(who, type_id)
        return row.name if row is not None else None

    async def resolve(self, who: Who, type_id: str, version: int | None) -> ResolvedVersion:
        """The version an extraction reads with: the one asked for, or the newest. Another team's type, or a version
        it does not have, is not found."""
        # The type and its version in one transaction; inside a caller's own one, part of it.
        async with isolation.request_transaction():
            row = await self._own(who, type_id)
            if row is None:
                raise DocumentTypeMissingError(type_id)
            n = version if version is not None else row.latest_version
            found = await self.store.version(type_id, n)
        if found is None:
            raise DocumentTypeMissingError(f"{type_id} v{n}")
        return {
            "id": type_id,
            "name": row.name,
            "version": n,
            "fields": dated(found.fields, found.date_order),
            "many": found.many,
            "reviewBelow": found.review_below,
            # The templates extraction tries; one flagged for a rebuild reads a field the version lacks.
            "templates": [t for t in found.templates or [] if not t.get(templates.NEEDS_REBUILD)],
            "allTemplates": found.templates or [],
            "checks": found.checks or [],
            "pageImages": bool(found.page_images),
            "offerAt": found.offer_at or DEFAULT_OFFER_AT,
        }

    # ── template suggestions ──

    async def _read_of(self, who: Who, type_id: str, row: ExtractionRow | None, extraction_id: str) -> templates.Read:
        if row is None or row.team != who.team:
            raise DocumentTypeMissingError(f"extraction {extraction_id}")
        if row.status != "done" or row.result is None:
            raise StateError(f"{extraction_id} is {row.status}; a suggestion reads finished reads only")
        doc_type = an_object(row.request.get("documentType") or {}, "documentType")
        if doc_type.get("id") != type_id:
            raise InvalidRequestError(f"{extraction_id} was not read as {type_id}")
        if "records" in row.result:
            raise InvalidRequestError(f"{extraction_id} reads several records; templates read one")
        layout = await self.extractor.layout_of(who, row)
        # Boxes found again from each quote with the current rules, so a read stored before a change to how boxes are
        # found (a date boxed with its label) still suggests the zone its value is printed in.
        fields: Json = {
            k: {kk: vv for kk, vv in an_object(f, f"field {k}").items() if kk not in ("boxes", "blocks")}
            for k, f in an_object(row.result.get("fields") or {}, "fields").items()
        }
        located = an_object(boxes.with_boxes({"fields": fields}, layout)["fields"], "fields")
        return templates.Read(
            layout, {k: boxes.boxes_of(an_object(f, f"field {k}").get("boxes")) for k, f in located.items()}
        )

    async def suggest_template(self, who: Who, type_id: str, extraction_ids: list[str]) -> dict[str, Any] | None:
        """A draft template from the team's finished reads of the type, and how it reads each of them. Nothing is
        saved: a builder saves the draft as a new version, so nothing goes live on its own."""
        self._may_write(who)
        # Gate: the type, the reads and the latest version in one transaction, closed before any layout is read, which
        # reads files-service when the layout is not stored.
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None:
                return None
            ids = list(dict.fromkeys(extraction_ids))
            if not 0 < len(ids) <= MAX_SUGGEST_READS:
                raise InvalidRequestError(f"extractionIds lists 1 to {MAX_SUGGEST_READS} reads")
            rows = [await self.extractor.store.get(i) for i in ids]
            version = await self.resolve(who, type_id, None)
        reads = [await self._read_of(who, type_id, r, i) for r, i in zip(rows, ids, strict=True)]
        tid = f"tpl_{uuid.uuid4().hex[:10]}"
        draft = templates.suggest(reads, template_id=tid)
        fields = [FIELD(f) for f in version["fields"]]
        checks: list[dict[str, Any]] = []
        for row, read in zip(rows, reads, strict=True):
            assert row is not None and row.result is not None
            found = templates.match(draft, read.layout) if draft["pages"] else templates.Miss(tid, 0.0, [])
            check: dict[str, Any] = {"extractionId": row.id, "matched": isinstance(found, templates.Match)}
            if isinstance(found, templates.Match):
                answers = templates.read(draft, found, read.layout)
                saved = cast(dict[str, dict[str, Any]], row.result.get("fields") or {})
                compared: dict[str, Any] = {}
                for f in fields:
                    key = f["key"]
                    want = saved.get(key, {}).get("value")
                    got = normalise(f, json_object(answers.get(key)).get("value"))[0] if answers.get(key) else None
                    if want is not None or got is not None:
                        compared[key] = {"expected": want, "got": got, "match": matches(f, want, got)}
                check["fields"] = compared
            else:
                check["missingAnchors"] = found.missing
            checks.append(check)
        return {"template": draft, "checks": checks}

    async def template_offers(self, who: Who, type_id: str) -> list[dict[str, Any]] | None:
        """Groups of at least the version's offerAt checked model reads of the type that share a layout and that no
        template of the latest version reads: where suggesting a template pays."""
        store = self.extractor.store
        # The type, its version and its reads in one transaction, closed before a layout is read from files-service.
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None:
                return None
            version = await self.resolve(who, type_id, None)
            recent = await store.recent_reads(who.team, type_id, last=TEMPLATE_OFFER_READS)
        current = version["templates"]
        groups: dict[str, list[ExtractionRow]] = {}
        for row in recent:
            result = row.result or {}
            if result.get("path") == PATH_TEMPLATE or result.get("needsReview") or "records" in result:
                continue
            fp = row.layout_fingerprint
            if fp is None:
                # A read saved before fingerprints were stored: its layout is read once and its fingerprint kept.
                fp = templates.fingerprint(await self._read_of(who, type_id, row, row.id))
                await store.keep_fingerprint(row.id, fp)
            groups.setdefault(fp, []).append(row)
        offers: list[dict[str, Any]] = []
        for fp, members in groups.items():
            if len(members) < version["offerAt"]:
                continue
            # One layout per offered group, from the layout cache, to ask whether a current template reads it.
            layout = await self.extractor.layout_of(who, members[0])
            if any(isinstance(templates.match(TEMPLATE(t), layout), templates.Match) for t in current):
                continue
            offers.append({"fingerprint": fp, "extractionIds": [m.id for m in members], "count": len(members)})
        return sorted(offers, key=lambda o: -o["count"])

    # ── samples ──

    async def add_sample(self, who: Who, type_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
        self._may_write(who)
        file_id = str(body.get("fileId") or "")
        expected = body.get("expected")
        # Gate: the type and its latest version, in one transaction closed before files-service is asked.
        async with isolation.request_transaction():
            row = await self._own(who, type_id)
            if row is None:
                return None
            latest = await self.store.version(type_id, row.latest_version)
        assert latest is not None
        keys = {str(f["key"]) for f in latest.fields}
        records = cast(list[Any], expected) if latest.many and isinstance(expected, list) else [expected]
        if (latest.many and not isinstance(expected, list)) or not all(isinstance(r, dict) for r in records):
            raise InvalidRequestError(
                "expected is {field: value}, or a list of them for a type reading several records"
            )
        unknown = sorted({k for r in records for k in cast(dict[str, Any], r)} - keys)
        if unknown:
            raise InvalidRequestError(
                f"expected names fields version {latest.version} does not have: {', '.join(unknown)}"
            )
        file = await self.files.readable(who, file_id)
        sample_id = f"smp_{uuid.uuid4().hex[:12]}"
        # Files keeps the file while the sample names it (files 5.3.4).
        await self.files.keep(who, file_id, ref_id=sample_id, name=row.name)
        sample = SampleRow(
            id=sample_id,
            type_id=type_id,
            file_id=file_id,
            name=file.name,
            expected=expected,
            added_by=who.actor,
            added_at=self.clock(),
        )
        async with isolation.request_transaction():
            await self.store.add_sample(who.tenant_id, sample)
        return _sample_view(sample)

    async def remove_sample(self, who: Who, type_id: str, sample_id: str) -> bool:
        self._may_write(who)
        # The sample's row goes in one transaction, committed before files-service is told to let the file go.
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None:
                return False
            gone = await self.store.remove_sample(type_id, sample_id)
        if gone is None:
            return False
        await self.files.release(who, gone.file_id, ref_id=sample_id)
        return True

    # ── examples ──

    async def examples(self, tenant: str, team: str, type_id: str, keys: list[str]) -> list[Json]:
        """What a read of the type is given: the newest few per field it asks, within the two caps."""
        found = await self.store.recent_examples(
            team, type_id, keys, per_field=EXAMPLES_PER_FIELD, total=EXAMPLES_IN_ALL
        )
        return [example_view(e) for e in found]

    async def list_examples(self, who: Who, type_id: str) -> list[Json] | None:
        """The type's examples in the caller's team, newest first, each printed line masked as the team masks personal
        data in what people see, and its corrected value too; the stored example, which reads are given, stays real."""
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None:
                return None
            rows = [example_view(e) for e in await self.store.examples(who.team, type_id)]
        if await self.extractor.masks(who):
            rows = [{**r, "line": masked(r["line"]), "value": masked(r["value"])} for r in rows]
        return rows

    async def remove_example(self, who: Who, type_id: str, example_id: str) -> bool:
        self._may_write(who)
        if await self._own(who, type_id) is None:
            return False
        return await self.store.remove_example(who.team, type_id, example_id)

    # ── tests ──

    async def estimate(self, who: Who, type_id: str, version: int) -> Json | None:
        """What testing the version spends before it is run: one model call per sample (two when a re-ask is
        needed), at most MAX_TEST_SAMPLES samples, priced at the extract alias's current price when it is known."""
        # Every row it reads in one transaction, closed before models-service is asked for the price.
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None or await self.store.version(type_id, version) is None:
                return None
            samples = min(len(await self.store.samples(type_id)), MAX_TEST_SAMPLES)
            # A reasoning model's output dwarfs a fixed guess (2,300 tokens a call against 600 on the baseline), so a
            # type read before is priced at what reading it measured, then the tenant's reads, then the guess.
            tokens, basis = (float(TOKENS_IN_PER_CALL), float(TOKENS_OUT_PER_CALL)), "default"
            extractions = self.extractor.store
            if (measured := await extractions.tokens_per_call(type_id)) is not None:
                tokens, basis = measured, "type"
            elif (measured := await extractions.tokens_per_call(None)) is not None:
                tokens, basis = measured, "tenant"
        price = await self.prices.price(ALIAS, tenant=who.tenant_id) if self.prices is not None else None
        out: Json = {
            "samples": samples,
            "calls": samples,
            "maxCalls": samples * 2,
            "alias": ALIAS,
            "capped": MAX_TEST_SAMPLES,
            "estimatedCost": None,
            "basis": basis,
        }
        if price is not None:
            per_call = (price[0] * Decimal(str(tokens[0])) + price[1] * Decimal(str(tokens[1]))) / Decimal(1_000_000)
            out["estimatedCost"] = str((per_call * samples).quantize(Decimal("0.0001")))
            out["maxCost"] = str((per_call * samples * 2).quantize(Decimal("0.0001")))
        return out

    async def start_test(self, who: Who, type_id: str, version: int) -> Json | None:
        self._may_write(who)
        # The run's row commits before the task that runs it starts, so the task finds it.
        async with isolation.request_transaction():
            if await self._own(who, type_id) is None or await self.store.version(type_id, version) is None:
                return None
            samples = await self.store.samples(type_id)
            if not samples:
                raise InvalidRequestError("add a sample before testing a version")
            test = TestRow(
                tenant_id=who.tenant_id,
                id=f"dtt_{uuid.uuid4().hex[:12]}",
                type_id=type_id,
                version=version,
                team=who.team,
                status="queued",
                samples=min(len(samples), MAX_TEST_SAMPLES),
                result=None,
                error=None,
                asked_by=who.actor,
                asked_at=self.clock(),
                finished_at=None,
            )
            await self.store.insert_test(test)
        await self._later(test)
        return _test_view(test)

    async def get_test(self, who: Who, type_id: str, test_id: str) -> Json | None:
        if await self._own(who, type_id) is None:
            return None
        found = await self.store.test(test_id)
        return _test_view(found) if found is not None and found.type_id == type_id else None

    async def resume(self) -> int:
        pending = await self.store.pending_tests()
        for t in pending:
            await self._later(t)
        return len(pending)

    async def drain(self) -> None:
        """Waits until no test run is running in this process (tests and shutdown)."""
        await self._pending.none()

    async def _later(self, test: TestRow) -> None:
        self._pending.add()
        await background.start(self._as_owner(test), key=READING_PROCESS)

    async def _as_owner(self, test: TestRow) -> None:
        """The run as the test's own tenant and team: a restart picks tests up with no request behind them. It runs on
        the supervisor, which shows a failure on /health/background."""
        try:
            with isolation.scope(test.tenant_id, test.team):
                await self._run(test)
        finally:
            self._pending.done()

    async def _run(self, test: TestRow) -> None:
        test_id = test.id
        who = Who(tenant_id=test.tenant_id, team=test.team, actor=test.asked_by)
        try:
            await self.store.set_test(test_id, {"status": "running"})
            version = await self.resolve(who, test.type_id, test.version)
            fields = [FIELD(f) for f in version["fields"]]
            samples = (await self.store.samples(test.type_id))[:MAX_TEST_SAMPLES]
            rows: list[dict[str, Any]] = []
            for s in samples:
                # Keyed by test and sample, so a test resumed after a restart reads the extractions it already made.
                _, answer = await self.extractor.ask(
                    who,
                    s.file_id,
                    {"documentTypeId": test.type_id, "version": test.version},
                    idempotency_key=f"{test_id}:{s.id}",
                    inline=True,
                )
                rows.append(self._compare(fields, version["many"], s, answer))
            await self.store.set_test(
                test_id, {"status": "done", "result": self._summary(fields, rows), "finished_at": self.clock()}
            )
        except Exception as e:
            log.warning("document type test failed", extra={"test": test_id, "error": str(e)})
            await self.store.set_test(test_id, {"status": "failed", "error": str(e), "finished_at": self.clock()})

    @staticmethod
    def _compare(
        fields: list[FieldDefinition], many: bool, sample: SampleRow, answer: dict[str, Any]
    ) -> dict[str, Any]:
        expected = sample.expected
        out: dict[str, Any] = {
            "sampleId": sample.id,
            "name": sample.name,
            "extractionId": answer.get("id"),
            "status": answer.get("status"),
        }
        # Whether a layout template read the sample, so a version's templates are seen to match before it is used.
        if answer.get("path"):
            out["path"] = answer["path"]
        if answer.get("templateId"):
            out["templateId"] = answer["templateId"]
        if answer.get("status") != "done":
            out["fields"] = {}
            return out
        wanted = cast(list[dict[str, Any]], expected) if many else [cast(dict[str, Any], expected)]
        got_records = cast(list[dict[str, Any]], answer.get("records") or []) if many else [answer]
        compared: dict[str, list[dict[str, Any]]] = {}
        for i, want in enumerate(wanted):
            got = cast(dict[str, Any], got_records[i]["fields"]) if i < len(got_records) else {}
            for f in fields:
                key = f["key"]
                if key not in want:
                    continue
                value = cast(dict[str, Any], got.get(key) or {}).get("value")
                compared.setdefault(key, []).append(
                    {"expected": want[key], "got": value, "match": matches(f, want[key], value)}
                )
        out["fields"] = compared
        return out

    @staticmethod
    def _summary(fields: list[FieldDefinition], rows: list[dict[str, Any]]) -> dict[str, Any]:
        per: dict[str, dict[str, Any]] = {}
        for f in fields:
            key = f["key"]
            seen = [c for r in rows for c in cast(dict[str, list[dict[str, Any]]], r["fields"]).get(key, [])]
            hit = sum(1 for c in seen if c["match"])
            per[key] = {
                "matches": hit,
                "misses": len(seen) - hit,
                "accuracy": round(hit / len(seen), 4) if seen else None,
            }
        total = sum(p["matches"] + p["misses"] for p in per.values())
        hits = sum(p["matches"] for p in per.values())
        return {"samples": rows, "fields": per, "accuracy": round(hits / total, 4) if total else None}


def masked(value: JsonValue) -> JsonValue:
    """`value` with every string in it masked as the team masks personal data; numbers and the shape stay."""
    if isinstance(value, str):
        return mask(value)
    if isinstance(value, list):
        return [masked(v) for v in value]
    if isinstance(value, dict):
        return {k: masked(v) for k, v in value.items()}
    return value


# A template is offered once this many checked reads share one layout, unless the type's
# version sets its own (`offerAt`).
DEFAULT_OFFER_AT = 5
# How many of a type's examples a read is given: the newest per field it asks, and at most this many in all.
EXAMPLES_PER_FIELD = 3
EXAMPLES_IN_ALL = 12
MIN_OFFER_AT = 2
# How many of a type's latest reads an offer looks through.
TEMPLATE_OFFER_READS = 200
MAX_SUGGEST_READS = 20


def default_document_types(files: Files, engine: Any, settings: Settings, extractor: Extractor) -> DocumentTypes:
    """On the extractor this app serves, which then resolves `documentTypeId` through them; prices from
    models-service when it is configured, else the estimate gives calls without a cost."""
    prices: Prices | None = None
    if settings.models is not None:
        try:
            prices = ModelsPrices(ServiceClient.for_settings(settings, service="documents", audience="models"))
        except ValueError as e:  # no service signing key outside dev
            log.warning("no service signing key; test estimates carry no cost", extra={"error": str(e)})
    types = DocumentTypes(DocumentTypesStore(engine), files, extractor, prices)
    extractor.types = types
    return types
