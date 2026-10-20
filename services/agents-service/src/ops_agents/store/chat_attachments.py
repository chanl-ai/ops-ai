"""Chat attachments (c-071): metadata and the parsed text, capped, of files a banker attaches to a chat message. The
bytes are in an ops_storage object store written by the interim `ChatFileStore` (activities/attachments.py); no blob
is kept here. Each row
belongs to its owner and team, so another person's file id reads as not found.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.schema import TENANT_SCOPED

from .base import metadata
from .tenancy import current_tenant, tenant_tx

chat_attachments = sa.Table(
    "chat_attachments",
    metadata,
    sa.Column("id", sa.String(64), primary_key=True),  # the interim chat file store's `fl_` id
    sa.Column("tenant_id", sa.String(64), nullable=False, default=current_tenant, server_default="local", index=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("owner_email", sa.String(320), nullable=False),
    sa.Column("name", sa.String(255), nullable=False),
    sa.Column("mime", sa.String(127), nullable=False),
    sa.Column("size", sa.Integer, nullable=False),
    # [{page, section, text}], capped at activities/attachments.MAX_TEXT_CHARS; `truncated` says text was cut.
    sa.Column("pages", sa.JSON, nullable=False),
    sa.Column("truncated", sa.Boolean, nullable=False),
    sa.Column("created_at", sa.String(32), nullable=False),
    info=TENANT_SCOPED,
)


class ChatAttachments:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def add(self, row: dict[str, Any]) -> None:
        async with tenant_tx(self.engine) as c:
            await c.execute(chat_attachments.insert().values(**row))

    async def owned(self, ids: list[str], *, owner_email: str, team_id: str) -> dict[str, dict[str, Any]]:
        """The rows among `ids` that `owner_email` holds in `team_id`, by id; any other id is simply absent."""
        if not ids:
            return {}
        q = chat_attachments.select().where(
            chat_attachments.c.id.in_(ids),
            chat_attachments.c.tenant_id == current_tenant(),
            chat_attachments.c.owner_email == owner_email,
            chat_attachments.c.team_id == team_id,
        )
        async with tenant_tx(self.engine) as c:
            return {str(r["id"]): dict(r) for r in (await c.execute(q)).mappings()}
