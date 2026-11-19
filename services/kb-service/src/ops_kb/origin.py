"""Where a source's item comes from, and the team its files are kept under."""

from __future__ import annotations

from dataclasses import dataclass, field

from .store.knowledge import ItemFetched, SourceRow


@dataclass(frozen=True)
class Origin:
    """Where an item came from: its key in its source (a file's name, or the system's id for a fetched item), the
    system's own title for it, and what else the fetch knows (its change marker, parent and address)."""

    path: str
    title: str | None = None
    extra: ItemFetched = field(default_factory=ItemFetched)
    # The ids the source system lets see this version, kept on the version.
    allowed: list[str] | None = None


def source_team(s: SourceRow) -> str:
    """The files-service team a source's files are stored under: the team that created the source."""
    return s.team_id or "team_ops"
