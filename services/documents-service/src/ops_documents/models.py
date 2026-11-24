# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""documents-service's request and response shapes, the same the console and the workflow step read."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import ConfigDict, Field

from ops_ingest.reading import OcrMode
from ops_service_kit.http import In, JsonValue, ListResult, Out
from ops_service_kit.names import Name


class Reply(Out):
    """A reply model. Every field is sent, defaulted ones too (no route drops a None), so its schema lists each as
    required and a generated client reads it as present."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class ExtractionRequest(In):
    """`fields` follow the Extract from file step's schema (key, label, type, required, description, enum,
    reviewBelow, alwaysReview); `many` answers one record per thing the document names."""

    # The files-service file to read, as the caller's team.
    file_id: str = Field(min_length=1, max_length=64)
    # The fields to read, or a document type whose version holds them.
    fields: list[dict[str, Any]] | None = None
    many: bool = False
    ocr: bool = False
    review_below: float | None = Field(default=None, ge=0, le=1)
    document_type_id: str | None = None
    # The document type's version; the newest when not given, and the answer names the one read.
    version: int | None = Field(default=None, ge=1)
    # Classify the file over the team's types first and read it with the kind found.
    detect: bool = False
    # What comes back: the fields asked for (today's read), or fields the model proposes from the first
    # `propose_pages` pages and then reads like any other. A file's full text is its reading (/v1/documents/readings).
    read: Literal["fields", "propose"] = "fields"
    # What the document is, in a few words, for a proposed read ("a supplier invoice").
    hint: str | None = Field(default=None, max_length=200)
    propose_pages: int | None = Field(default=None, ge=1, le=20)
    # Read only the first pages; every page when not given.
    max_pages: int | None = Field(default=None, ge=1)
    # A ceiling on the page text sent to the model (about 4 characters a token): pages past it are not read, and the
    # answer says `partial`.
    max_tokens: int | None = Field(default=None, ge=1)


class CorrectionIn(In):
    value: Any
    # The record's position, for an extraction of several records.
    record: int | None = Field(default=None, ge=0)


class DocumentTypeRef(Out):
    id: str
    version: int
    # The type's name when it was read, so whatever records the read names it without asking again.
    name: str | None = None


class ExtractionError(Out):
    code: str | None
    message: str | None
    details: list[str] | None = None


class Classification(Out):
    """Which of the team's document types a file is: the model's choice and how sure it is, or none.
    `needsReview` when none fits or the confidence is under the floor."""

    type_id: str | None
    name: str | None
    confidence: float | None
    reason: str
    needs_review: bool
    floor: float


class TemplateMiss(Out):
    template_id: str
    score: float
    missing_anchors: list[str]


class ExtractionCorrection(Out):
    """A person's value for a field, with the value and confidence it replaced (`record` for a read of several)."""

    field: str
    record: int | None
    original: JsonValue
    original_confidence: float
    corrected: JsonValue
    corrected_by: str
    corrected_at: datetime


class ReadIncomplete(Out):
    """A read no model reply answered: cut off at the output limit, empty of an answer, declined or filtered. A
    declined reply's first words are kept, masked when the team masks personal data."""

    reason: Literal["cut_off", "empty", "declined", "filtered"]
    step: str
    tries: int
    refusal: str | None = None


class ImageCall(Out):
    """A model call that carried page images: its step, the pages shown, how many images and the alias."""

    step: str
    pages: list[int]
    images: int
    alias: str


class Extraction(Out):
    """An extraction's state, and its scored answer once done: what the Extract from file step's outputs carry."""

    id: str
    file_id: str
    status: Literal["queued", "running", "done", "failed", "unreadable"]
    outcome: Literal["ok", "review", "unreadable", "unknown", "incomplete"] | None = None
    # Why a read with outcome incomplete has no answer, the step whose reply ended it and how many asks were made.
    incomplete: ReadIncomplete | None = None
    # Why the one re-read of doubtful fields had no answer; the first values stand, under review.
    reread_incomplete: Literal["cut_off", "empty", "declined", "filtered"] | None = None
    # Each field's answer: value, extractedValue, confidence, needsReview and its citation, as the engine scores it.
    fields: dict[str, JsonValue] | None = None
    records: list[dict[str, JsonValue]] | None = None
    count: int | None = None
    # The field keys under review, or the record positions for a read of several.
    needs_review: list[str | int] | None = None
    floor: float | None = None
    # The field definitions the read asked for, as the type version or the request holds them.
    asked: list[dict[str, JsonValue]] | None = Field(default=None, alias="schema")
    # How many pages an unreadable file has; a full-text read's pages, each {number, text, tables}.
    pages: int | list[dict[str, JsonValue]] | None = None
    # A full-text read's text, page after page in reading order.
    text: str | None = None
    # A proposed read's fields in the document type's shape and a suggested name.
    proposal: dict[str, JsonValue] | None = None
    # The pages read when a limit applied, and whether the token ceiling left pages unread.
    read_pages: int | None = None
    partial: bool | None = None
    error: ExtractionError | None = None
    corrections: list[ExtractionCorrection] | None = None
    document_type: DocumentTypeRef | None = None
    classification: Classification | None = None
    # How the read was made: from a layout template's zones, with its id, or by the model, with the best
    # template's score and missing anchors when the type version has templates and none matched.
    path: Literal["template", "model"] | None = None
    template_id: str | None = None
    template_miss: TemplateMiss | None = None
    # Every model call that carried a page image: {step, pages, images, alias}; and why none was sent though
    # the version and the team allowed it (the alias is not cleared for images).
    image_calls: list[ImageCall] | None = None
    image_refused: str | None = None
    # The tokens a template read's re-read of failed fields spent, kept out of the test estimate's average.
    reread_tokens: dict[str, int] | None = None


class ClassifyIn(In):
    file_id: str = Field(min_length=1, max_length=64)
    ocr: bool = False


class DocumentTypeIn(In):
    """A new document type and its version 1. `id` is the caller's (lowercase, e.g. levy_notice) or generated."""

    id: str | None = Field(default=None, max_length=64)
    name: Name
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
    # Layout templates for version 1, as on DocumentTypeVersionIn.
    templates: list[dict[str, Any]] = Field(default_factory=list[dict[str, Any]], max_length=20)
    # Checks across fields for version 1, as on DocumentTypeVersionIn.
    checks: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Show the model the page image, as on DocumentTypeVersionIn; off when not given.
    page_images: bool = False
    # How many checked reads of one layout offer a template, as on DocumentTypeVersionIn; 5 when not given.
    offer_at: int | None = Field(default=None, ge=2, le=1000)
    note: str | None = Field(default=None, max_length=500)
    # The file a proposed read was made from, kept as the type's first sample.
    sample_file_id: str | None = Field(default=None, min_length=1, max_length=64)


class DocumentTypeVersionIn(In):
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
    # Layout templates: {id, pages: [{page, anchors: [{text, box, required?}], zones: [{field, box}]}]}, boxes
    # as [x0, top, x1, bottom] fractions of the page. A file printed from one is read from its zones with no model call.
    # Left out, the latest version's templates are carried forward, each flagged needsRebuild when a field it reads is
    # gone; given (even empty), they replace them.
    templates: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Checks across fields: {id, kind: sum, fields, equals, tolerance?} or {id, kind: before, earlier, later}.
    # Left out on a new version, the latest version's carry forward (dropping one naming a field the version lacks).
    checks: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    # Show the model the page image of an OCR'd page, and a crop of each doubtful field on its re-read, where
    # the team's pageImages policy and the model alias allow it. Turning it on needs documents.manage; left out, the
    # latest version's setting carries forward.
    page_images: bool | None = None
    # How many checked reads sharing one layout offer a template: 5 unless set; left out, the latest carries.
    offer_at: int | None = Field(default=None, ge=2, le=1000)
    note: str | None = Field(default=None, max_length=500)


class DocumentTypeVersion(Out):
    """A saved version. Its field definitions, layout templates and checks are the documents the builder wrote, held
    as JSON: the engine (`ops_extract`) reads them and DocumentTypeVersionIn bounds what is saved."""

    version: int
    fields: list[dict[str, JsonValue]]
    many: bool
    review_below: float | None
    date_order: Literal["MDY", "DMY"]
    templates: list[dict[str, JsonValue]]
    checks: list[dict[str, JsonValue]]
    page_images: bool = False
    offer_at: int
    note: str | None
    created_by: str
    created_at: datetime


class TemplateSuggestIn(In):
    """The team's finished reads of the type a suggestion is drawn from."""

    extraction_ids: list[str] = Field(min_length=1, max_length=20)


class TemplateSuggestion(Out):
    """A draft template, saved by nobody until a builder posts it as a new version, and how it reads each read it came
    from: matched or the anchors it missed, and per field the read's value against the template's."""

    # A layout template as a version holds it (anchors, zones), and per source read what it matched and missed.
    template: dict[str, JsonValue]
    checks: list[dict[str, JsonValue]]


class TemplateOffer(Out):
    """Checked model reads of the type that share one layout no current template reads."""

    fingerprint: str
    extraction_ids: list[str]
    count: int


class SampleIn(In):
    file_id: str
    # {field: value}, or a list of them in order for a type reading several records.
    expected: Any


class DocumentTypeExample(Out):
    """A correction a person made on a read of the type, which later reads of it are given. `line` is where the
    value was printed, masked as the team masks personal data; `record` is the record's position, for several."""

    id: str
    field: str
    line: str | None
    value: JsonValue
    extraction_id: str
    record: int | None
    corrected_by: str
    created_at: datetime


class Sample(Out):
    id: str
    file_id: str
    name: str
    # {field: value}, or a list of them in order for a type reading several records.
    expected: JsonValue
    added_by: str
    added_at: datetime


class DocumentTypeRow(Out):
    id: str
    name: str
    description: str | None
    latest_version: int


class DocumentTypeList(ListResult[DocumentTypeRow]):
    """A page of the team's types on the shared list contract."""

    # Whether the caller may add a type in the team, so the console never decides it from a role.
    can_create: bool


class DocumentType(DocumentTypeRow):
    team: str
    created_by: str
    created_at: datetime
    versions: list[DocumentTypeVersion]
    samples: list[Sample]
    # Whether the caller may add versions and samples and run tests on this type.
    can_edit: bool


class TestEstimate(Out):
    """What testing a version spends, before it runs: priced at the type's measured tokens per call, the
    tenant's when the type has none yet, else a fixed guess; `basis` says which."""

    samples: int
    calls: int
    max_calls: int
    alias: str
    capped: int
    estimated_cost: str | None
    max_cost: str | None = None
    basis: Literal["type", "tenant", "default"] = "default"


class LayoutIn(In):
    file_id: str = Field(min_length=1, max_length=64)
    # Read a page with no text layer through OCR; a layout read with OCR is cached apart from one read without.
    ocr: bool = False


class LayoutPage(Out):
    number: int
    # Points; None for formats with no pages (DOCX, HTML).
    width: float | None
    height: float | None
    source: Literal["text", "ocr", "mixed", "none"]


class LayoutCell(Out):
    id: str
    row: int
    col: int
    row_span: int
    col_span: int
    text: str
    # [x0, y0, x1, y1] as fractions of the page from the top left; None without a page.
    box: list[float] | None


class LayoutBlock(Out):
    id: str
    page: int
    kind: Literal["title", "heading", "line", "paragraph", "table"]
    text: str
    box: list[float] | None
    order: int
    cells: list[LayoutCell] | None = None


class LayoutWord(Out):
    page: int
    text: str
    box: list[float]
    # 1.0 on a text layer; Tesseract's recognition confidence on an OCR'd page.
    conf: float


class Layout(Out):
    """A file's layout: pages, blocks in reading order with their table cells, and words."""

    engine: str
    pages: list[LayoutPage]
    blocks: list[LayoutBlock]
    words: list[LayoutWord]


class FieldScore(Out):
    """How a version read one field across the samples."""

    matches: int
    misses: int
    accuracy: float | None


class SampleComparison(Out):
    expected: JsonValue
    got: JsonValue
    match: bool


class SampleResult(Out):
    """One sample's read in a test: its extraction, how it was read and each field against what it should be."""

    sample_id: str
    name: str
    extraction_id: str | None
    status: str | None
    path: Literal["template", "model"] | None = None
    template_id: str | None = None
    fields: dict[str, list[SampleComparison]]


class TestResult(Out):
    accuracy: float | None
    fields: dict[str, FieldScore]
    samples: list[SampleResult]


class TestRun(Out):
    id: str
    type_id: str
    version: int
    status: Literal["queued", "running", "done", "failed"]
    samples: int
    asked_by: str
    asked_at: datetime
    result: TestResult | None = None
    error: str | None = None


class ReadingIn(In):
    file_id: str = Field(min_length=1, max_length=64)
    # off: text layers only; auto: scans and the picture parts of mixed pages; always: every page, for a bad text layer.
    ocr: OcrMode = "auto"
    # A Tesseract language, or several joined by + (eng+fra).
    language: str = Field("eng", min_length=2, max_length=64, pattern=r"^[A-Za-z_]+(\+[A-Za-z_]+)*$")


class ReadingSettingsOut(Out):
    ocr: OcrMode
    language: str


class ReadingError(Out):
    code: str
    message: str


# A reading's parts as this service answers them: the same fields as ops_ingest's reading models, owned here so the
# reply is an `Out` (frozen, extra forbidden) and the contract does not move when the reader's models do.
Box = list[float]


class ReadingLine(Out):
    text: str
    box: Box | None = None


class ReadingCell(Out):
    id: str
    row: int
    col: int
    row_span: int = 1
    col_span: int = 1
    text: str
    box: Box | None = None
    header: bool = False


class ReadingBlock(Out):
    id: str
    kind: Literal["title", "heading", "paragraph", "table"]
    text: str
    box: Box | None = None
    order: int = 0
    level: int | None = None
    lines: list[ReadingLine] = Field(default_factory=list[ReadingLine])
    cells: list[ReadingCell] = Field(default_factory=list[ReadingCell])
    caption: str | None = None
    sheet: str | None = None
    read_by: Literal["text", "ocr"] = "text"
    furniture: bool = False
    main: bool = False


class ReadingWord(Out):
    text: str
    box: Box
    confidence: float


class ReadingFormField(Out):
    name: str
    value: str
    kind: Literal["text", "checkbox", "choice", "signature"]
    page: int
    box: Box | None = None


class ReadingOcrQuality(Out):
    mean: float
    low_share: float
    words: int


class ReadingPage(Out):
    number: int
    width: float | None = None
    height: float | None = None
    source: Literal["text", "ocr", "mixed", "none"]
    image_share: float = 0.0
    text: str = ""
    blocks: list[ReadingBlock] = Field(default_factory=list[ReadingBlock])
    words: list[ReadingWord] = Field(default_factory=list[ReadingWord])
    form_fields: list[ReadingFormField] = Field(default_factory=list[ReadingFormField])
    ocr: ReadingOcrQuality | None = None
    unread_reason: str | None = None
    warnings: list[str] = Field(default_factory=list[str])
    duration_ms: int = 0


class FileFacts(Out):
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    title: str | None = None
    author: str | None = None
    created: str | None = None
    modified: str | None = None
    paged: bool = True
    removed_chars: int = 0
    warnings: list[str] = Field(default_factory=list[str])


class FileReading(Out):
    """A file's reading: queued, reading or none (never asked) with its progress, failed with the reason, or done with
    the file's facts and its pages (all of them, or the one asked for). Keyed by the file's bytes and settings, so every
    caller that reads the same file gets this one reading."""

    file_id: str
    digest: str
    status: Literal["none", "queued", "reading", "done", "failed"]
    reader_version: str
    settings: ReadingSettingsOut
    pages_total: int | None
    pages_done: int
    error: ReadingError | None = None
    facts: FileFacts | None = None
    duration_ms: int | None = None
    pages: list[ReadingPage] | None = None


class PurgeIn(In):
    file_id: str = Field(min_length=1, max_length=64)


class Purged(Out):
    """What was removed for a deleted file: its extractions (with their corrections), the samples naming it, and the
    readings of its bytes once no other file of the workspace holds them."""

    extractions: int
    samples: int
    readings: int = 0
