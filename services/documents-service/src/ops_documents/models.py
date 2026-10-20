# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's request and response shapes, the same the console and the workflow step read (c-235, c-236)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class ExtractionRequest(Model):
    """`fields` follow the Extract from file step's schema (key, label, type, required, description, enum,
    reviewBelow, alwaysReview); `many` answers one record per thing the document names (c-235)."""

    # The files-service file to read, as the caller's team.
    file_id: str = Field(min_length=1, max_length=64)
    # The fields to read, or a document type whose version holds them (c-236).
    fields: list[dict[str, Any]] | None = None
    many: bool = False
    ocr: bool = False
    review_below: float | None = Field(default=None, ge=0, le=1)
    document_type_id: str | None = None
    # The document type's version; the newest when not given, and the answer names the one read.
    version: int | None = Field(default=None, ge=1)
    # Classify the file over the team's types first and read it with the kind found (c-249).
    detect: bool = False


class CorrectionIn(Model):
    value: Any
    # The record's position, for an extraction of several records.
    record: int | None = Field(default=None, ge=0)


class DocumentTypeRef(Model):
    id: str
    version: int
    # The type's name when it was read, so whatever records the read names it without asking again (c-378).
    name: str | None = None


class ExtractionError(Model):
    code: str | None
    message: str | None
    details: list[str] | None = None


class Classification(Model):
    """Which of the team's document types a file is (c-249): the model's choice and how sure it is, or none.
    `needsReview` when none fits or the confidence is under the floor."""

    type_id: str | None
    name: str | None
    confidence: float | None
    reason: str
    needs_review: bool
    floor: float


class TemplateMiss(Model):
    template_id: str
    score: float
    missing_anchors: list[str]


class Extraction(Model):
    """An extraction's state, and its scored answer once done: what the Extract from file step's outputs carry."""

    id: str
    file_id: str
    status: Literal["queued", "running", "done", "failed", "unreadable"]
    outcome: Literal["ok", "review", "unreadable", "unknown"] | None = None
    fields: dict[str, Any] | None = None
    records: list[dict[str, Any]] | None = None
    count: int | None = None
    needs_review: list[Any] | None = None
    floor: float | None = None
    asked: list[dict[str, Any]] | None = Field(default=None, alias="schema")
    pages: int | None = None
    error: ExtractionError | None = None
    corrections: list[dict[str, Any]] | None = None
    document_type: DocumentTypeRef | None = None
    classification: Classification | None = None
    # How the read was made (c-253): from a layout template's zones, with its id, or by the model, with the best
    # template's score and missing anchors when the type version has templates and none matched.
    path: Literal["template", "model"] | None = None
    template_id: str | None = None
    template_miss: TemplateMiss | None = None
    # Every model call that carried a page image (c-295): {step, pages, images, alias}; and why none was sent though
    # the version and the team allowed it (the alias is not cleared for images).
    image_calls: list[dict[str, Any]] | None = None
    image_refused: str | None = None
    # The tokens a template read's re-read of failed fields spent (c-296), kept out of the test estimate's average.
    reread_tokens: dict[str, int] | None = None


class ClassifyIn(Model):
    file_id: str = Field(min_length=1, max_length=64)
    ocr: bool = False


class DocumentTypeIn(Model):
    """A new document type and its version 1. `id` is the caller's (lowercase, e.g. levy_notice) or generated."""

    id: str | None = Field(default=None, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    fields: list[dict[str, Any]] = Field(
        min_length=1,
        description=(
            "Each field: key, label, type (text, number, money, date, enum), required, description, options (enum), "
            "reviewBelow, alwaysReview, keyField (a key field: a review shows it first and requires it checked), "
            "and its rules: pattern, emptyWhen, clean."
        ),
    )
    many: bool = False
    review_below: float | None = Field(default=None, ge=0, le=1)
    # How a numeric date reads: MDY (03/04/2026 is March 4, US documents) or DMY (4 March); MDY when not given.
    date_order: Literal["MDY", "DMY"] = "MDY"
    # Layout templates for version 1 (c-253), as on DocumentTypeVersionIn.
    templates: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]], max_length=20)
    # Checks across fields for version 1 (c-296), as on DocumentTypeVersionIn.
    checks: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Show the model the page image (c-295), as on DocumentTypeVersionIn; off when not given.
    page_images: bool = False
    # How many checked reads of one layout offer a template (c-254), as on DocumentTypeVersionIn; 5 when not given.
    offer_at: int | None = Field(default=None, ge=2, le=1000)
    note: str | None = Field(default=None, max_length=500)


class DocumentTypeVersionIn(Model):
    fields: list[dict[str, Any]] = Field(
        min_length=1,
        description=(
            "Each field: key, label, type (text, number, money, date, enum), required, description, options (enum), "
            "reviewBelow, alwaysReview, keyField (a key field: a review shows it first and requires it checked), "
            "and its rules: pattern, emptyWhen, clean."
        ),
    )
    many: bool = False
    review_below: float | None = Field(default=None, ge=0, le=1)
    # How a numeric date reads: MDY (03/04/2026 is March 4, US documents) or DMY (4 March); MDY when not given.
    date_order: Literal["MDY", "DMY"] = "MDY"
    # Layout templates (c-253): {id, pages: [{page, anchors: [{text, box, required?}], zones: [{field, box}]}]}, boxes
    # as [x0, top, x1, bottom] fractions of the page. A file printed from one is read from its zones with no model call.
    # Left out, the latest version's templates are carried forward, each flagged needsRebuild when a field it reads is
    # gone; given (even empty), they replace them.
    templates: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Checks across fields (c-296): {id, kind: sum, fields, equals, tolerance?} or {id, kind: before, earlier, later}.
    # Left out on a new version, the latest version's carry forward (dropping one naming a field the version lacks).
    checks: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Show the model the page image of an OCR'd page, and a crop of each doubtful field on its re-read (c-295), where
    # the team's pageImages policy and the model alias allow it. Turning it on needs documents.manage; left out, the
    # latest version's setting carries forward.
    page_images: bool | None = None
    # How many checked reads sharing one layout offer a template (c-254): 5 unless set; left out, the latest carries.
    offer_at: int | None = Field(default=None, ge=2, le=1000)
    note: str | None = Field(default=None, max_length=500)


class DocumentTypeVersion(Model):
    version: int
    fields: list[dict[str, Any]]
    many: bool
    review_below: float | None
    date_order: Literal["MDY", "DMY"]
    templates: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    page_images: bool = False
    offer_at: int
    note: str | None
    created_by: str
    created_at: datetime


class TemplateSuggestIn(Model):
    """The team's finished reads of the type a suggestion is drawn from (c-254)."""

    extraction_ids: list[str] = Field(min_length=1, max_length=20)


class TemplateSuggestion(Model):
    """A draft template, saved by nobody until a builder posts it as a new version, and how it reads each read it came
    from: matched or the anchors it missed, and per field the read's value against the template's."""

    template: dict[str, Any]
    checks: list[dict[str, Any]]


class TemplateOffer(Model):
    """Checked model reads of the type that share one layout no current template reads (c-254)."""

    fingerprint: str
    extraction_ids: list[str]
    count: int


class SampleIn(Model):
    file_id: str
    # {field: value}, or a list of them in order for a type reading several records.
    expected: Any


class DocumentTypeExample(Model):
    """A correction a person made on a read of the type, which later reads of it are given (c-297). `line` is where the
    value was printed, masked as the team masks personal data; `record` is the record's position, for several."""

    id: str
    field: str
    line: str | None
    value: Any
    extraction_id: str
    record: int | None
    corrected_by: str
    created_at: datetime


class Sample(Model):
    id: str
    file_id: str
    name: str
    expected: Any
    added_by: str
    added_at: datetime


class DocumentTypeRow(Model):
    id: str
    name: str
    description: str | None
    latest_version: int


class DocumentTypeList(Model):
    items: list[DocumentTypeRow]
    # Whether the caller may add a type in the team (c-243), so the console never decides it from a role.
    can_create: bool


class DocumentType(DocumentTypeRow):
    team: str
    created_by: str
    created_at: datetime
    versions: list[DocumentTypeVersion]
    samples: list[Sample]
    # Whether the caller may add versions and samples and run tests on this type.
    can_edit: bool


class TestEstimate(Model):
    """What testing a version spends, before it runs (c-236): priced at the type's measured tokens per call, the
    tenant's when the type has none yet, else a fixed guess (c-247); `basis` says which."""

    samples: int
    calls: int
    max_calls: int
    alias: str
    capped: int
    estimated_cost: str | None
    max_cost: str | None = None
    basis: Literal["type", "tenant", "default"] = "default"


class LayoutIn(Model):
    file_id: str = Field(min_length=1, max_length=64)
    # Read a page with no text layer through OCR; a layout read with OCR is cached apart from one read without.
    ocr: bool = False


class LayoutPage(Model):
    number: int
    # Points; None for formats with no pages (DOCX, HTML).
    width: float | None
    height: float | None
    source: Literal["text", "ocr", "none"]


class LayoutCell(Model):
    id: str
    row: int
    col: int
    row_span: int
    col_span: int
    text: str
    # [x0, y0, x1, y1] as fractions of the page from the top left; None without a page.
    box: list[float] | None


class LayoutBlock(Model):
    id: str
    page: int
    kind: Literal["title", "heading", "line", "paragraph", "table"]
    text: str
    box: list[float] | None
    order: int
    cells: list[LayoutCell] | None = None


class LayoutWord(Model):
    page: int
    text: str
    box: list[float]
    # 1.0 on a text layer; Tesseract's recognition confidence on an OCR'd page.
    conf: float


class Layout(Model):
    """A file's layout (c-247): pages, blocks in reading order with their table cells, and words."""

    engine: str
    pages: list[LayoutPage]
    blocks: list[LayoutBlock]
    words: list[LayoutWord]


class TestRun(Model):
    id: str
    type_id: str
    version: int
    status: Literal["queued", "running", "done", "failed"]
    samples: int
    asked_by: str
    asked_at: datetime
    result: dict[str, Any] | None = None
    error: str | None = None


class PurgeIn(Model):
    file_id: str = Field(min_length=1, max_length=64)


class Purged(Model):
    """What was removed for a deleted file: its extractions (with their corrections) and the samples naming it."""

    extractions: int
    samples: int
