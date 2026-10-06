# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import pytest

from knowledge_ingest.metadata import (
    MappingError,
    MetadataMapping,
    chunks_for_kb,
    evaluate_holds,
    resolve_metadata,
)
from knowledge_ingest.models import IngestSettings
from knowledge_ingest.parsers import parse
from knowledge_ingest.split import split

COLLECTION_PROFILE = ["department", "owner", "version", "effective_date"]


def mapping(key: str, source: str) -> MetadataMapping:
    return MetadataMapping.model_validate({"key": key, "from": source})


def resolve(fields: dict[str, str], *extra: MetadataMapping) -> dict[str, str]:
    return resolve_metadata(
        [mapping("effective_date", "field:Effective"), *extra],
        fields=fields,
        collection="cards",
        source_owner="cards-ops",
        source_sensitivity="internal",
        content_digest="sha256:abcdef0123456789",
    ).values


def test_held_item_emits_no_chunks() -> None:
    values = resolve({"Effective": "   "})
    holds = evaluate_holds(values, collection_profile=COLLECTION_PROFILE, kb_profiles={"Cards": [], "Branch": []})
    result = split(parse(b"# Fees\n\nThe annual fee is $95.", filename="f.md"), IngestSettings())
    assert result.chunks
    assert holds.held_reason() == (["effective_date"], ["Cards", "Branch"])
    assert chunks_for_kb(result, holds, "Cards", values) == []
    assert chunks_for_kb(result, holds, "Branch", values) == []


def test_kb_only_key_holds_that_kb_only() -> None:
    values = resolve({"Effective": "2026-01-01"})
    holds = evaluate_holds(
        values, collection_profile=COLLECTION_PROFILE, kb_profiles={"Cards": ["product"], "Branch": []}
    )
    result = split(parse(b"# Fees\n\nThe annual fee is $95.", filename="f.md"), IngestSettings())
    assert chunks_for_kb(result, holds, "Cards", values) == []
    served = chunks_for_kb(result, holds, "Branch", values)
    assert len(served) == 1 and served[0].metadata["department"] == "cards"
    assert holds.held_reason() == (["product"], ["Cards"])


@pytest.mark.parametrize("key", ["department", "sensitivity", "owner"])
def test_ai_mapping_refused_for_trust_keys(key: str) -> None:
    with pytest.raises(MappingError) as err:
        resolve({}, mapping(key, f"ai:{key}"))
    assert err.value.code == "mapping_not_allowed"


def test_mapping_cannot_lower_sensitivity() -> None:
    values = resolve_metadata(
        [mapping("sensitivity", "static:internal")],
        fields={},
        collection="cards",
        source_owner="cards-ops",
        source_sensitivity="confidential",
        document_label="restricted",
    ).values
    assert values["sensitivity"] == "restricted"
