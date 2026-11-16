"""A knowledge base's Documents table (GET /v1/knowledge-bases/{kb_id}/documents) chosen, counted and paged in SQL.

A document is an item of a source the base reads. Its type, collection and sensitivity are columns of the item and its
source; its shown status is a CASE of the stored one; its freshness and tags are the source's, given by the service
(freshness is worked out from the source's schedule) and read here as (source id, value) pairs, so every filter and
facet is a statement whatever the number of documents. The page's items are then shaped by the service.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa

from ops_service_kit.listing import ListParams
from ops_store.listing import ListPage, Several, list_page
from ops_store.team_scope import team_visible

from .knowledge import ITEM_COLUMNS, ItemRow, KnowledgeStore, kb_base_sources, kb_items, kb_sources

# The console's word for an item being read.
SHOWN_STATUS = {"reading": "processing"}
WORD_MIMES = {"application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
SHEET_MIMES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
SLIDE_MIMES = {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def doc_type(mime: str, source_type: str, has_url: bool) -> str:
    """What a document is, as the Documents table's Type names it: written in the console, from an app, a web page (a
    pushed page with its address counts), or by its file type. `doc_type_sql` is the same rule in SQL."""
    if source_type == "text":
        return "typed"
    if source_type == "tool":
        return "app"
    if mime == "text/html" or source_type == "web" or has_url:
        return "web"
    if mime == "application/pdf":
        return "pdf"
    if mime in WORD_MIMES:
        return "word"
    if mime in SHEET_MIMES:
        return "spreadsheet"
    if mime in SLIDE_MIMES:
        return "slides"
    if mime.startswith("text/"):
        return "text"
    return "other"


def doc_type_sql() -> sa.ColumnElement[str]:
    i, s = kb_items.c, kb_sources.c
    has_url = sa.and_(i.url.is_not(None), i.url != "")
    return sa.case(
        (s.type == "text", "typed"),
        (s.type == "tool", "app"),
        (sa.or_(i.mime == "text/html", s.type == "web", has_url), "web"),
        (i.mime == "application/pdf", "pdf"),
        (i.mime.in_(sorted(WORD_MIMES)), "word"),
        (i.mime.in_(sorted(SHEET_MIMES)), "spreadsheet"),
        (i.mime.in_(sorted(SLIDE_MIMES)), "slides"),
        (i.mime.like("text/%"), "text"),
        else_="other",
    )


def _pairs(name: str, pairs: Sequence[tuple[str, str]]) -> sa.Select[*tuple[Any, ...]]:
    """(source id, value) pairs as a select; none at all is a select of no rows, as VALUES needs one row."""
    if not pairs:
        return sa.select(kb_sources.c.id, kb_sources.c.type).where(sa.false(), team_visible(kb_sources))
    values = sa.values(sa.column("source_id", sa.String), sa.column("value", sa.String), name=name).data(list(pairs))
    return sa.select(values.c.source_id, values.c.value)


async def document_page(
    store: KnowledgeStore,
    tenant: str,
    kb_id: str,
    params: ListParams,
    *,
    freshness: Mapping[str, str],
    tags: Mapping[str, Sequence[str]],
) -> tuple[ListPage, list[ItemRow]]:
    """One page of the base's documents, oldest first and then by id, searched by title or path. Each filter keeps
    rows matching any of its values, and each facet counts its values over the rows the other filters keep. The
    base's links, its sources and the items each carry the tenant and the acting team."""
    i, s, link = kb_items.c, kb_sources.c, kb_base_sources.c
    linked = sa.select(link.source_id).where(
        link.tenant_id == tenant, link.kb_id == kb_id, team_visible(kb_base_sources)
    )
    query = (
        sa.select(*ITEM_COLUMNS)
        .select_from(kb_items.join(kb_sources, sa.and_(s.tenant_id == i.tenant_id, s.id == i.source_id)))
        .where(i.tenant_id == tenant, i.source_id.in_(linked), team_visible(kb_items), team_visible(kb_sources))
    )
    source = sa.select(s.id, s.collection).where(s.tenant_id == tenant, team_visible(kb_sources))
    shown = sa.case(*((i.status == stored, name) for stored, name in SHOWN_STATUS.items()), else_=i.status)
    kind = doc_type_sql()
    async with store.tx() as conn:
        page = await list_page(
            conn,
            query,
            params,
            search=[i.title, i.path],
            default_sort=i.created_at.asc(),
            filters={"sourceId": i.source_id, "status": shown, "docType": kind},
            facets={"sourceId": i.source_id, "status": shown, "docType": kind},
            several={
                "collection": Several(i.source_id, source),
                "sensitivity": Several(i.source_id, source.with_only_columns(s.id, s.sensitivity)),
                "freshness": Several(i.source_id, _pairs("freshness", sorted(freshness.items()))),
                "tags": Several(
                    i.source_id, _pairs("tags", sorted({(sid, t) for sid, ts in tags.items() for t in ts}))
                ),
            },
        )
    return page, [ItemRow.model_validate(row) for row in page["data"]]
