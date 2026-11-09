"""A source's settings for every stage it owns: how its files are read, how they are cleaned and split, which items
it takes in and what metadata each piece carries. They live in the source's `settings` column, are validated when
saved, and are applied by the stage that owns each part: reading by documents-service with the source's OCR mode,
cleaning and splitting by `ops_ingest`, rules at sync.

A source made before its settings were saved answers with its kind's defaults, so what the console shows is what a
sync applies. `index_key` is the digest an item records as `indexed_with`: an item whose digest differs was split
under older settings and is rebuilt from its stored reading."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic.alias_generators import to_camel

from ops_ingest import IngestSettings, InvalidIngestError, validate_settings
from ops_ingest.metadata import MappingError, MetadataMapping, validate_mapping
from ops_ingest.models import AI_STEPS
from ops_ingest.rules import Rule
from ops_ingest.split import preset_for
from ops_store.schedule import InvalidSchedule, checked

OcrMode = Literal["off", "auto", "always"]


class _Model(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Parsing(_Model):
    """How documents-service reads the source's files. Vision (a model transcribing page images) is not offered."""

    ocr: OcrMode = "auto"
    tables: bool = True
    vision: Literal[False] = False


class Cleaning(_Model):
    """What is removed between reading and splitting. Furniture and main content act on the blocks the reading marked,
    so changing them splits the stored reading again and reads nothing."""

    furniture: bool = False
    main_content: bool = False
    site_repeats: bool = False
    duplicates: Literal["flag", "skip"] = "flag"


class SourceSettings(_Model):
    parsing: Parsing = Field(default_factory=Parsing)
    cleaning: Cleaning = Field(default_factory=Cleaning)
    ingest: IngestSettings
    rules: list[Rule] = Field(default_factory=list[Rule])
    metadata_mapping: list[MetadataMapping] = Field(default_factory=list[MetadataMapping])
    # When it syncs on its own (ops_store.schedule); None: the kind's default (a plugin's own schedule for its source).
    schedule: dict[str, Any] | None = None
    # The most one sync or rebuild may spend on model calls for its AI steps, in the environment's currency;
    # models-service refuses past it from what it recorded, and the rest of the pieces are indexed without them.
    ai_ceiling: float = Field(default=5.0, ge=0.1, le=500.0)


class InvalidSettings(ValueError):
    """A settings change the API refuses with `invalid_settings`; the message names the setting."""


# Splitting at headings with the title and section path on each piece: what every file source was indexed with
# before settings could be saved, so an existing source's pieces stay as they were.
FILE_SPLIT = ["structure", "context_headers"]
# Kinds whose content is pages of a site or an app, where menus, footers and banners are noise.
WEB_KINDS = ("web",)
CONNECTOR_KINDS = ("tool",)


def defaults(kind: str, *, ocr: str = "auto", model: str = "bank-standard") -> SourceSettings:
    """A new source's settings for its kind; `ocr` is the environment's default (kb_ocr)."""
    web = kind in WEB_KINDS
    connector = kind in CONNECTOR_KINDS
    strategies = ["clean", "structure", "context_headers"] if web else FILE_SPLIT
    ingest = IngestSettings.model_validate(
        {
            "preset": preset_for(cast(Any, strategies)),
            "strategies": strategies,
            "size": 400,
            "overlap": 40,
            "childSize": 120,
            "questionsPerSection": 3,
            "model": model,
        }
    )
    cleaning = Cleaning(furniture=web or connector, main_content=web, site_repeats=web)
    return SourceSettings(parsing=Parsing(ocr=cast(OcrMode, ocr)), cleaning=cleaning, ingest=ingest)


def stored(kind: str, raw: dict[str, Any] | None, *, ocr: str = "auto") -> SourceSettings:
    """The source's saved settings over its kind's defaults."""
    base = defaults(kind, ocr=ocr)
    if not raw:
        return base
    return SourceSettings.model_validate({**wire(base), **raw})


def wire(s: SourceSettings) -> dict[str, Any]:
    return s.model_dump(by_alias=True, mode="json")


# A website is checked once a day by default; files sync when someone asks.
WEB_SCHEDULE: dict[str, Any] = {"kind": "daily", "time": "02:00", "tz": "UTC"}


def merged(current: SourceSettings, patch: dict[str, Any]) -> SourceSettings:
    """`current` with the parts `patch` names replaced (a nested part merged key by key), validated as a whole.
    The AI-step approval is the knowledge owner's decision on its own route, so a settings save never changes it;
    an AI step added since the approval waits for it again."""
    data = wire(current)
    for key, value in patch.items():
        if key == "schedule":
            # A schedule is replaced whole: a daily one's time means nothing to an hourly one.
            data[key] = value
        elif isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**cast(dict[str, Any], data[key]), **cast(dict[str, Any], value)}
        else:
            data[key] = value
    if isinstance(data.get("ingest"), dict):
        ingest = cast(dict[str, Any], data["ingest"])
        ingest["approval"] = wire(current)["ingest"]["approval"]
        ingest["preset"] = preset_for(cast(Any, ingest.get("strategies") or []))
    try:
        out = SourceSettings.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise InvalidSettings(f"{where}: {first['msg']}") from e
    try:
        validate_settings(out.ingest)
        for m in out.metadata_mapping:
            validate_mapping(m)
        if out.schedule is not None:
            out.schedule = checked(out.schedule)
    except (InvalidIngestError, MappingError, InvalidSchedule) as e:
        raise InvalidSettings(str(e)) from e
    added = [s for s in out.ingest.strategies if s in AI_STEPS and s not in out.ingest.approval.approved_steps]
    if added and out.ingest.approval.status != "pending":
        out.ingest.approval.status = "pending"
    return out


def split_settings(s: SourceSettings) -> IngestSettings:
    """The split as it runs: with page furniture cleaned, the boilerplate lines (`clean`) go too."""
    if s.cleaning.furniture and "clean" not in s.ingest.strategies:
        return s.ingest.model_copy(update={"strategies": ["clean", *s.ingest.strategies]})
    return s.ingest


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def index_key(s: SourceSettings, repeats: list[str] | None = None) -> str:
    """What an item's pieces depend on beyond its reading: cleaning, splitting, the AI steps approved, metadata, and
    (with lines repeated across the site dropped) which lines those are. Rules decide which items are in, not how one
    is split, so they are not part of it."""
    ingest = s.ingest.model_dump(mode="json", exclude={"approval"})
    approved = sorted(s.ingest.approval.approved_steps) if s.ingest.approval.status == "approved" else []
    return _digest(
        {
            "cleaning": s.cleaning.model_dump(mode="json"),
            "ingest": ingest,
            "approved": approved,
            "metadata": [m.model_dump(mode="json", by_alias=True) for m in s.metadata_mapping],
            **({"repeats": repeats} if s.cleaning.site_repeats and repeats else {}),
        }
    )


Rebuild = Literal["none", "split", "read"]


def rebuild_for(before: SourceSettings, after: SourceSettings) -> Rebuild:
    """What a settings change runs again: a new OCR mode reads the files again (a new reading per file), a split,
    cleaning or metadata change splits the stored readings again, and rules or anything else rebuilds nothing now
    (the next sync takes in or removes what the rules allow)."""
    if before.parsing.ocr != after.parsing.ocr:
        return "read"
    if index_key(before) != index_key(after):
        return "split"
    return "none"
