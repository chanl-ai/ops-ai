# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 chanl-ai
"""Content digests, duplicates across sources, and effective-dated versions (spec 1.6, 15.3 to 15.6)."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

_INVISIBLE = re.compile("[\u200b-\u200d\u2060\ufeff\u00ad]")

VersionStatus = Literal["current", "superseded", "scheduled"]


def normalise_text(text: str) -> str:
    """NFKC, invisible characters removed, whitespace collapsed. Case and punctuation are content."""
    text = unicodedata.normalize("NFKC", text)
    text = _INVISIBLE.sub("", text)
    return " ".join(text.split())


def content_digest(text: str) -> str:
    """SHA-256 of the normalised text after `clean`."""
    return "sha256:" + hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()


def is_new_version(previous_digest: str | None, digest: str) -> bool:
    """Spec 1.6: re-syncing unchanged content creates no version and no re-embedding."""
    return previous_digest != digest


def permission_scope_digest(principals: list[str] | None, mode: str = "selected") -> str:
    scope = mode if principals is None else mode + ":" + ",".join(sorted(set(principals)))
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class DedupeKey:
    """Two item versions with equal keys share one set of index units (spec 15.3)."""

    content_digest: str
    collection: str
    sensitivity: str
    permission_scope: str


@dataclass(frozen=True)
class DedupeDecision:
    item_version_id: str
    canonical_id: str
    duplicate_of: str | None


@dataclass
class DedupeRegistry:
    """First indexed is canonical; later versions with the same key record `duplicate_of`.

    Duplicates in different permission scopes stay separate, so a person entitled to only one of them
    still finds it. The service backs this with the `index_units` key in spec 5.18.
    """

    _canonical: dict[DedupeKey, str] = field(default_factory=dict[DedupeKey, str])
    also_in: dict[str, list[str]] = field(default_factory=dict[str, list[str]])

    def register(self, item_version_id: str, key: DedupeKey) -> DedupeDecision:
        canonical = self._canonical.get(key)
        if canonical is None or canonical == item_version_id:
            self._canonical[key] = item_version_id
            return DedupeDecision(item_version_id, item_version_id, None)
        self.also_in.setdefault(canonical, []).append(item_version_id)
        return DedupeDecision(item_version_id, canonical, canonical)


class VersionInput(BaseModel):
    version_id: str
    effective_date: dt.date
    supersedes: str | None = None


class VersionState(BaseModel):
    version_id: str
    status: VersionStatus
    superseded_by: str | None
    effective_from: dt.date
    #: The next version's effective date; `None` while open.
    effective_to: dt.date | None


class UnresolvedSupersedesError(ValueError):
    """`supersedes` names a version outside the chain; spec 1.4 holds the item."""


def _depth(version: VersionInput, by_id: dict[str, VersionInput]) -> int:
    depth, seen = 0, {version.version_id}
    current = version
    while current.supersedes is not None and current.supersedes in by_id and current.supersedes not in seen:
        seen.add(current.supersedes)
        current = by_id[current.supersedes]
        depth += 1
    return depth


def compute_versions(chain: list[VersionInput], today: dt.date) -> list[VersionState]:
    """Statuses for one linked chain. Order is by effective date, not by when versions were ingested;
    on equal dates a version that supersedes another comes after it."""
    by_id = {v.version_id: v for v in chain}
    for v in chain:
        if v.supersedes is not None and v.supersedes not in by_id:
            raise UnresolvedSupersedesError(f"{v.version_id} supersedes {v.supersedes}, which is not in the chain")
    ordered = sorted(chain, key=lambda v: (v.effective_date, _depth(v, by_id)))
    in_force = [v for v in ordered if v.effective_date <= today]
    current_id = in_force[-1].version_id if in_force else None

    states: list[VersionState] = []
    for i, v in enumerate(ordered):
        following = ordered[i + 1] if i + 1 < len(ordered) else None
        if v.effective_date > today:
            status: VersionStatus = "scheduled"
        elif v.version_id == current_id:
            status = "current"
        else:
            status = "superseded"
        states.append(
            VersionState(
                version_id=v.version_id,
                status=status,
                superseded_by=following.version_id if status == "superseded" and following else None,
                effective_from=v.effective_date,
                effective_to=following.effective_date if following else None,
            )
        )
    return states
