"""Chat thread search on plain columns (c-069; portability rule D5): each chat thread's title, agent name, last reply
and every question asked, kept in `chat_search` and rewritten when the thread is created, renamed or answered. Search
is a case-insensitive LIKE on those columns, so it runs the same on PostgreSQL, SQLite, MySQL and Azure SQL; nothing
is read out of JSON.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_team, current_tenant, tenant_tx

# Questions kept per thread for search; a thread past this is searched on its newest questions.
MAX_QUESTIONS_CHARS = 20_000

chat_search = sa.Table(
    "chat_search",
    metadata,
    sa.Column("thread_id", sa.String(64), primary_key=True),
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("team_id", sa.String(64), nullable=False, index=True),
    sa.Column("title", sa.String(200), nullable=False),
    sa.Column("agent_name", sa.String(200), nullable=False),
    sa.Column("preview", sa.String(400), nullable=False),
    sa.Column("questions", sa.Text, nullable=False),
    sa.Column("updated_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


def _like(text: str) -> str:
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def index_thread(engine: AsyncEngine, row: dict[str, Any]) -> None:
    """Replaces the thread's search row. Delete then insert in one transaction, so no dialect's upsert is needed."""
    questions = str(row["questions"])[-MAX_QUESTIONS_CHARS:]
    values = {**row, "questions": questions, "title": str(row["title"])[:200], "preview": str(row["preview"])[:400]}
    async with tenant_tx(engine) as c:
        await c.execute(
            chat_search.delete().where(
                chat_search.c.thread_id == row["thread_id"], chat_search.c.tenant_id == current_tenant()
            )
        )
        await c.execute(chat_search.insert().values(**values))


async def indexed_ids(engine: AsyncEngine, thread_ids: list[str]) -> set[str]:
    if not thread_ids:
        return set()
    q = sa.select(chat_search.c.thread_id).where(
        chat_search.c.thread_id.in_(thread_ids), chat_search.c.tenant_id == current_tenant()
    )
    async with tenant_tx(engine) as c:
        return {str(i) for i in (await c.execute(q)).scalars()}


def matching_query(search: str) -> sa.Select[tuple[str]]:
    """The search as one plain-column statement: lower(column) LIKE '%term%' with `%` and `_` taken literally."""
    pattern = _like(search)
    has = [
        sa.func.lower(col).like(pattern, escape="\\")
        for col in (
            chat_search.c.title,
            chat_search.c.agent_name,
            chat_search.c.preview,
            chat_search.c.questions,
        )
    ]
    q = sa.select(chat_search.c.thread_id).where(chat_search.c.tenant_id == current_tenant(), sa.or_(*has))
    if (team := current_team()) is not None:
        q = q.where(chat_search.c.team_id == team)
    return q


async def matching_threads(engine: AsyncEngine, search: str) -> set[str]:
    """Ids of chat threads in the current tenant and team whose title, agent, last reply or any question contains
    `search`, case-insensitive."""
    async with tenant_tx(engine) as c:
        return {str(i) for i in (await c.execute(matching_query(search))).scalars()}
