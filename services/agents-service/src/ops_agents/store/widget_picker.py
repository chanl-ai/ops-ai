"""The agent page's widget picker read: each widget an agent may pin, with the content of the version a pin takes, in
one query rather than one version read per widget. The tables are store/widgets.py's."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa
from pydantic import BaseModel, JsonValue

from ops_store import Guarantee
from ops_store.rows import rows
from ops_store.search import contains
from ops_store.team_scope import team_visible

from .graphs import mine
from .tenancy import RuntimeStore
from .widgets import registry_widget_versions, registry_widgets


class Pinnable(BaseModel):
    """A widget the picker offers: `shown` is its published version, else its newest, and `content` that version's."""

    id: str
    name: str
    shown: int
    content: dict[str, JsonValue] | None


class WidgetPicker(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def pinnable(
        self, teams: list[str], search: str, offset: int, limit: int, ids: list[str] | None = None
    ) -> list[Pinnable]:
        """Widgets an agent may newly pin (published, not retired) in `teams`, by name then id, searched and limited in
        the query; `ids` returns exactly those in `teams`, so a pin already held keeps its label."""
        w, v = registry_widgets.c, registry_widget_versions.c
        shown = sa.func.coalesce(w.published_version, w.version)
        joined = registry_widgets.outerjoin(
            registry_widget_versions, sa.and_(v.tenant_id == w.tenant_id, v.widget_id == w.id, v.version == shown)
        )
        scope = (w.team_id.in_(teams), mine(registry_widgets), team_visible(registry_widgets))
        if ids is not None:
            chosen: tuple[sa.ColumnElement[bool], ...] = (w.id.in_(ids),)
        else:
            chosen = (contains(w.name, search), w.published_version.is_not(None), w.retired_reason.is_(None))
        q = (
            sa.select(w.id, w.name, shown.label("shown"), v.content)
            .select_from(joined)
            .where(*scope, *chosen)
            .order_by(sa.func.lower(w.name), w.id)
            .offset(offset)
            .limit(limit)
        )
        async with self.tx() as c:
            return await rows(c, q, Pinnable)
