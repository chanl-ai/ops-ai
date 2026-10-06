# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
from __future__ import annotations

import datetime as dt

import pytest

from knowledge_ingest.dedupe import (
    DedupeKey,
    DedupeRegistry,
    UnresolvedSupersedesError,
    VersionInput,
    compute_versions,
    content_digest,
    permission_scope_digest,
)

TODAY = dt.date(2026, 10, 6)


def key(text: str, scope: list[str]) -> DedupeKey:
    return DedupeKey(content_digest(text), "cards", "internal", permission_scope_digest(scope))


def test_identical_content_shares_units() -> None:
    registry = DedupeRegistry()
    first = registry.register("sharepoint:v1", key("Annual fee is $95.", ["cards-team"]))
    second = registry.register("upload:v1", key("Annual fee is  $95.\n", ["cards-team"]))
    assert first.duplicate_of is None
    assert second.duplicate_of == "sharepoint:v1"
    assert registry.also_in == {"sharepoint:v1": ["upload:v1"]}


def test_permission_scopes_not_merged() -> None:
    registry = DedupeRegistry()
    registry.register("a:v1", key("Annual fee is $95.", ["cards-team"]))
    other = registry.register("b:v1", key("Annual fee is $95.", ["branch-staff"]))
    assert other.duplicate_of is None


def test_digest_normalisation() -> None:
    base = content_digest("Annual fee is $95.")
    assert content_digest("  Annual\u00a0fee is\u200b $95.\n\n") == base
    assert content_digest("Annual fee is $96.") != base
    assert base.startswith("sha256:") and len(base) == 7 + 64


def test_later_effective_date_supersedes() -> None:
    # Ingested out of order: the newer version arrives first.
    chain = [
        VersionInput(version_id="v2", effective_date=dt.date(2026, 6, 1), supersedes="v1"),
        VersionInput(version_id="v1", effective_date=dt.date(2026, 1, 1)),
    ]
    states = {s.version_id: s for s in compute_versions(chain, TODAY)}
    assert states["v2"].status == "current"
    assert states["v1"].status == "superseded"
    assert states["v1"].superseded_by == "v2"
    assert states["v1"].effective_to == dt.date(2026, 6, 1)
    assert states["v2"].effective_to is None


def test_future_version_is_scheduled() -> None:
    chain = [
        VersionInput(version_id="v1", effective_date=dt.date(2026, 1, 1)),
        VersionInput(version_id="v2", effective_date=dt.date(2026, 12, 1), supersedes="v1"),
    ]
    states = {s.version_id: s for s in compute_versions(chain, TODAY)}
    assert states["v1"].status == "current"
    assert states["v2"].status == "scheduled"
    assert states["v1"].effective_to == dt.date(2026, 12, 1)


def test_unresolved_supersedes_raises() -> None:
    with pytest.raises(UnresolvedSupersedesError):
        compute_versions([VersionInput(version_id="v2", effective_date=TODAY, supersedes="missing")], TODAY)
