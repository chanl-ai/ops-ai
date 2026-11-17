"""What reading one file left on its item, as a sync counts and reports it."""

from __future__ import annotations

from dataclasses import dataclass

from .store.knowledge import ItemChanges, ItemRow, ItemWrite, RunError


@dataclass(frozen=True)
class Settled:
    """What reading one file left on its item: what a sync counts and reports."""

    id: str
    title: str
    status: str
    digest: str
    error_class: str | None = None
    error: str | None = None
    content_digest: str | None = None
    unchanged: bool = False


def settled_row(row: ItemRow, over: ItemChanges, *, unchanged: bool = False) -> Settled:
    """The item `row` is once `over` is written to it."""
    return Settled(
        row.id,
        over.get("title", row.title),
        over.get("status", row.status),
        over.get("digest", row.digest),
        over.get("error_class", row.error_class),
        over.get("error", row.error),
        over.get("content_digest", row.content_digest),
        unchanged,
    )


def settled_new(item: ItemWrite) -> Settled:
    return Settled(
        item["id"],
        item["title"],
        item["status"],
        item["digest"],
        item.get("error_class"),
        item.get("error"),
        item.get("content_digest"),
    )


def parse_error(done: Settled) -> RunError:
    """The run's line for a document that could not be read or indexed."""
    return {
        "itemId": done.id,
        "itemTitle": done.title,
        "phase": "parse",
        "errorClass": done.error_class,
        "message": done.error,
    }
