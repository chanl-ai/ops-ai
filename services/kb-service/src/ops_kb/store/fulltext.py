"""The keyword lane of the knowledge search (retrieval.py), on PostgreSQL full-text search. Another database has no
full-text index on the units yet (kb_0016), so there the lane is not ready and each result names it skipped."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Protocol, TypedDict

import sqlalchemy as sa
from sqlalchemy import RowMapping

from ops_store.store import Store

from .knowledge import ROLE


class NarrowedScope(Protocol):
    """What the lanes read of one base's scope (retrieval.Scope)."""

    @property
    def collections(self) -> Sequence[str]: ...

    @property
    def source_ids(self) -> Sequence[str]: ...

    @property
    def tags_include(self) -> Sequence[str]: ...

    @property
    def tags_exclude(self) -> Sequence[str]: ...

    @property
    def include_untagged(self) -> bool: ...

    @property
    def match(self) -> str: ...

    @property
    def conditions(self) -> Sequence[tuple[str, str, str]]: ...

    def narrows(self) -> bool: ...


class Narrowing(Protocol):
    """What the lanes read of a search (retrieval.Search): each base's scope and the request's one collection. A
    protocol, so the store never imports the retrieval layer above it."""

    @property
    def scopes(self) -> Mapping[str, NarrowedScope]: ...

    @property
    def collection(self) -> str | None: ...


# The bases' threshold is the least share of the question's terms a unit holds. At the default, half: "mortgage
# brokers selling travel insurance" shares two of five terms with a rate sheet and is not answered by it. With at least
# two terms in the question, a passage must also share two, so one common word ("mortgage") never carries a passage on
# its own. A long prompt (a workflow agent step with its instructions) is scored against a bounded term set, or the
# answering passage falls under the floor because the extra words drown it.
MIN_SHARED_TERMS = 2
TERM_CAP = 6


def scope_sql(kb_ids: list[str], how: Narrowing | None) -> tuple[str, dict[str, str]]:
    """The SQL each lane adds to keep a base's pieces within its own scope (`Search.scopes`) and the request's
    collection, with its parameters. It reads the aliases both lanes use: `l` the base's link to a source, `s` the
    source, `i` the item and `c` the piece. Tags are the source's; metadata is the piece's, compared as text."""
    params: dict[str, str] = {}

    def bind(value: str) -> str:
        name = f"sc{len(params)}"
        params[name] = value
        return f":{name}"

    def listed(values: Sequence[str]) -> str:
        return ", ".join(bind(v) for v in values)

    tags, meta = "CAST(s.tags AS jsonb)", "CAST(c.metadata AS jsonb)"
    untagged = f"jsonb_array_length({tags}) = 0"
    parts: list[str] = []
    for kb_id in kb_ids:
        sc = how.scopes.get(kb_id) if how is not None else None
        rule = [f"l.kb_id = {bind(kb_id)}"]
        if sc is not None and sc.narrows():
            if sc.collections:
                rule.append(f"s.collection IN ({listed(sc.collections)})")
            if sc.source_ids:
                rule.append(f"i.source_id IN ({listed(sc.source_ids)})")
            if sc.tags_exclude:
                rule.append(f"NOT jsonb_exists_any({tags}, CAST(ARRAY[{listed(sc.tags_exclude)}] AS text[]))")
            if sc.tags_include:
                given = f"jsonb_exists_any({tags}, CAST(ARRAY[{listed(sc.tags_include)}] AS text[]))"
                rule.append(f"({given} OR {untagged})" if sc.include_untagged else given)
            elif not sc.include_untagged:
                rule.append(f"NOT {untagged}")
            conditions = [_condition(f"({meta} ->> {bind(k)})", op, v, bind, listed) for k, op, v in sc.conditions]
            if conditions:
                rule.append("(" + (" OR " if sc.match == "any" else " AND ").join(conditions) + ")")
        parts.append("(" + " AND ".join(rule) + ")")
    clause = "(" + " OR ".join(parts) + ")" if parts else "TRUE"
    if how is not None and how.collection:
        clause += f" AND s.collection = {bind(how.collection)}"
    return clause, params


def _condition(field: str, op: str, value: str, bind: Callable[[str], str], listed: Callable[[list[str]], str]) -> str:
    """One metadata condition, exact and typed as text: a date compares as its ISO text."""
    if op == "exists":
        return f"{field} IS NOT NULL"
    if op == "is_not":
        return f"COALESCE({field}, '') <> {bind(value)}"
    if op == "one_of":
        return f"{field} IN ({listed([v.strip() for v in value.split(',') if v.strip()] or [''])})"
    if op in ("before", "after"):
        return f"{field} {'<' if op == 'before' else '>'} {bind(value)}"
    return f"{field} = {bind(value)}"


# Every index unit of a live piece of an indexed item in a source the knowledge base reads, scored against the
# question's lexemes. A piece is returned by its best unit (its own text, a child, a question).
_SEARCH = """
    WITH q AS (
        SELECT array(SELECT DISTINCT unnest(tsvector_to_array(to_tsvector('english', :question)))) AS terms
    ),
    hits AS (
        SELECT l.kb_id, c.id AS chunk_id, c.item_id, c.version, c.title, c.section, c.page, c.text,
               u.kind AS unit_kind, u.text AS unit_text, i.file_id, i.url, i.verified,
               (SELECT count(*) FROM unnest(q.terms) t WHERE u.tsv @@ to_tsquery('english', quote_literal(t)))
                   AS shared,
               cardinality(q.terms) AS total,
               ts_rank_cd(u.tsv, to_tsquery('english', array_to_string(
                   array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))) AS rank
        FROM q, kb_units u
        JOIN kb_chunks c ON c.tenant_id = u.tenant_id AND c.id = u.chunk_id AND c.withdrawn_at IS NULL
        JOIN kb_items i ON i.tenant_id = c.tenant_id AND i.id = c.item_id AND i.status = 'indexed'
             AND i.duplicate_of IS NULL
        JOIN kb_base_sources l ON l.tenant_id = i.tenant_id AND l.source_id = i.source_id
        JOIN kb_sources s ON s.tenant_id = i.tenant_id AND s.id = i.source_id
        WHERE u.tenant_id = :tenant AND l.kb_id IN :kb_ids AND {scope}
          AND cardinality(q.terms) > 0
          AND u.tsv @@ to_tsquery('english', array_to_string(
              array(SELECT quote_literal(t) FROM unnest(q.terms) t), ' | '))
    )
    SELECT * FROM hits
    WHERE shared >= LEAST(:min_shared, total)
      AND CAST(shared AS FLOAT) / LEAST(total, :term_cap) >= :floor
    ORDER BY CAST(shared AS FLOAT) / LEAST(total, :term_cap) DESC, rank DESC
    LIMIT :limit
    """
# Units read per piece asked for: a piece's own text, a child and a question can all match, and each piece is
# returned once.
OVERFETCH = 4


class PieceHit(TypedDict):
    """The columns both lanes read for a matching unit: its base, its piece and the item and file it comes from."""

    kb_id: str
    chunk_id: str
    item_id: str
    version: int
    title: str
    section: str
    page: int | None
    text: str
    unit_kind: str
    unit_text: str
    file_id: str | None
    url: str | None
    verified: bool


class KeywordHit(PieceHit):
    """A unit the keyword lane matched: the terms it shares of the question's `total`, its rank, and `lane_score`, the
    share of the terms it holds."""

    shared: int
    total: int
    rank: float
    lane_score: float


def piece_of(r: RowMapping) -> PieceHit:
    """The piece columns of a result row."""
    return PieceHit(
        kb_id=r["kb_id"],
        chunk_id=r["chunk_id"],
        item_id=r["item_id"],
        version=r["version"],
        title=r["title"],
        section=r["section"],
        page=r["page"],
        text=r["text"],
        unit_kind=r["unit_kind"],
        unit_text=r["unit_text"],
        file_id=r["file_id"],
        url=r["url"],
        verified=r["verified"],
    )


class KeywordLane(Store):
    """The keyword lane: units holding at least `threshold` of the question's terms, best first, each with its share as
    `lane_score`. As the tenant role, so the team policy keeps another team's chunks out of the search."""

    role = ROLE

    def ready(self) -> bool:
        """Whether this database searches the units' text: PostgreSQL alone carries their tsv column."""
        return self.engine.dialect.name == "postgresql"

    async def hits(
        self,
        tenant: str,
        kb_ids: list[str],
        question: str,
        *,
        threshold: float,
        limit: int,
        how: Narrowing | None = None,
    ) -> list[KeywordHit]:
        if not kb_ids or not question.strip():
            return []
        scope, scoped = scope_sql(kb_ids, how)
        search = sa.text(_SEARCH.replace("{scope}", scope)).bindparams(sa.bindparam("kb_ids", expanding=True))
        params = {
            **scoped,
            "tenant": tenant,
            "kb_ids": kb_ids,
            "question": question,
            "limit": limit * OVERFETCH,
            "floor": threshold,
            "min_shared": MIN_SHARED_TERMS,
            "term_cap": TERM_CAP,
        }
        async with self.tx() as c:
            rows = (await c.execute(search, params)).mappings().all()
        return [
            KeywordHit(
                **piece_of(r),
                shared=r["shared"],
                total=r["total"],
                rank=r["rank"],
                lane_score=float(r["shared"]) / float(min(r["total"], TERM_CAP)),
            )
            for r in rows
        ]
