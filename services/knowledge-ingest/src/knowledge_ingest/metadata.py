# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Item metadata: mapping from source fields and static values, and the required-metadata hold.

Spec 4.3, 5.1 and 15.7 to 15.9. Keys are snake_case, the form chunks and filters use.

| Key | Value comes from |
|---|---|
| `department` | The source's collection, always. A mapping for it is refused |
| `sensitivity` | The highest of the source's sensitivity, the document's own label and any mapped value |
| `owner` | A mapping, else the source owner |
| `version` | A mapping, else the source's version label, else a content digest prefix |
| anything else | A mapping (`static:` or `field:`); `ai:` is listed in `pending_ai` for the AI step |
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from knowledge_ingest.models import Chunk, SplitResult

Sensitivity = Literal["internal", "confidential", "restricted"]
_SENSITIVITY_ORDER: dict[str, int] = {"internal": 0, "confidential": 1, "restricted": 2}
# Spec 1.3: these describe who may see and own a document, so they never come from its body.
_NOT_FROM_BODY = frozenset({"department", "sensitivity", "owner"})


class MappingError(ValueError):
    def __init__(self, code: Literal["mapping_not_allowed", "invalid_mapping"], message: str) -> None:
        super().__init__(message)
        self.code = code


class MetadataMapping(BaseModel):
    """Console `MetadataMapping`: `from` is `static:<value>`, `field:<source field>` or `ai:<key>`."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
    key: str
    from_: str = Field(alias="from")


def validate_mapping(mapping: MetadataMapping) -> None:
    kind, sep, _ = mapping.from_.partition(":")
    if not sep or kind not in {"static", "field", "ai"}:
        raise MappingError("invalid_mapping", f"Mapping for {mapping.key} must start with static:, field: or ai:")
    if mapping.key == "department":
        raise MappingError("mapping_not_allowed", "Department comes from the source's collection and cannot be mapped.")
    if kind == "ai" and mapping.key in _NOT_FROM_BODY:
        raise MappingError("mapping_not_allowed", f"{mapping.key} cannot be extracted from the document by AI.")


class ResolvedMetadata(BaseModel):
    values: dict[str, str]
    #: Keys mapped with `ai:`, to be filled by the AI step when the source supplied none (spec 14.15).
    pending_ai: list[str] = Field(default_factory=list[str])


def max_sensitivity(*levels: str | None) -> Sensitivity:
    known = [lv for lv in levels if lv in _SENSITIVITY_ORDER]
    best = max(known, key=lambda lv: _SENSITIVITY_ORDER[lv], default="internal")
    return best  # pyright: ignore[reportReturnType]


def resolve_metadata(
    mappings: list[MetadataMapping],
    *,
    fields: dict[str, str],
    collection: str,
    source_owner: str,
    source_sensitivity: Sensitivity,
    document_label: str | None = None,
    source_version: str | None = None,
    content_digest: str | None = None,
) -> ResolvedMetadata:
    values: dict[str, str] = {}
    pending_ai: list[str] = []
    for mapping in mappings:
        validate_mapping(mapping)
        kind, _, arg = mapping.from_.partition(":")
        if kind == "static":
            values[mapping.key] = arg
        elif kind == "field":
            value = fields.get(arg, "").strip()
            if value:
                values[mapping.key] = value
        else:
            pending_ai.append(mapping.key)

    values["department"] = collection
    values["sensitivity"] = max_sensitivity(source_sensitivity, document_label, values.get("sensitivity"))
    values.setdefault("owner", source_owner)
    if "version" not in values:
        if source_version:
            values["version"] = source_version
        elif content_digest:
            values["version"] = content_digest.removeprefix("sha256:")[:12]
    pending_ai = [k for k in pending_ai if k not in values]
    return ResolvedMetadata(values=values, pending_ai=pending_ai)


def missing_keys(values: dict[str, str], required: list[str]) -> list[str]:
    return [k for k in required if not values.get(k, "").strip()]


class KbHold(BaseModel):
    kb_name: str
    status: Literal["indexable", "held"]
    missing: list[str] = Field(default_factory=list[str])


class HoldReport(BaseModel):
    """Per knowledge base, whether the item may be indexed. Console `HeldReason` is `held_reason()`."""

    collection_missing: list[str]
    by_kb: dict[str, KbHold]

    def held_reason(self) -> tuple[list[str], list[str]] | None:
        held = [h for h in self.by_kb.values() if h.status == "held"]
        if not held:
            return None
        missing = sorted({k for h in held for k in h.missing})
        return missing, [h.kb_name for h in held]

    def is_held(self, kb_name: str) -> bool:
        return self.by_kb[kb_name].status == "held"


def evaluate_holds(
    values: dict[str, str],
    *,
    collection_profile: list[str],
    kb_profiles: dict[str, list[str]],
) -> HoldReport:
    """Spec 1.1 and 15.7: missing collection keys hold the item everywhere; a key only a knowledge base
    adds holds it for that knowledge base and leaves it searchable in the others."""
    collection_missing = missing_keys(values, collection_profile)
    by_kb: dict[str, KbHold] = {}
    for kb_name, extra in kb_profiles.items():
        missing = list(dict.fromkeys(collection_missing + missing_keys(values, extra)))
        by_kb[kb_name] = KbHold(kb_name=kb_name, status="held" if missing else "indexable", missing=missing)
    return HoldReport(collection_missing=collection_missing, by_kb=by_kb)


def chunks_for_kb(result: SplitResult, holds: HoldReport, kb_name: str, values: dict[str, str]) -> list[Chunk]:
    """The chunks a knowledge base may index for this item: none while it is held there."""
    if holds.is_held(kb_name):
        return []
    return [c.model_copy(update={"metadata": {**values, **c.metadata}}) for c in result.chunks]
