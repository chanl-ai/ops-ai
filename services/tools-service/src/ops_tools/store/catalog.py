"""The tool catalogue of one tenant as the events that would build it, for another service's copy to rebuild from
(`ops_store.copies.resync`): one `tool.module.published` per module and one `tool.team_state.changed` per team
granted it, each at the module's revision. A page is a run of modules in id order, so a page never repeats or skips
one while modules are added or removed."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from ops_service_kit.http import Out
from ops_store.outbox import ToolPublished, ToolTeamStateChanged
from ops_store.team_scope import any_team

from .modules import Aggregate, ModuleStore, TitleOf, catalog_of, team_grants, tool_modules

# Why the read crosses teams: a copy holds every team's modules of the tenant, and each read of it applies the team.
RESYNC = "a copy of the tool catalogue is rebuilt from every team's modules of the tenant"


class CatalogEvent(Out):
    """One event of the catalogue as the outbox would carry it; a consumer reads it as an `ops_store.outbox.Event`.
    The team is null for a workspace-level module."""

    name: str
    tenant_id: str
    team_id: str | None
    revision: int
    payload: Annotated[ToolPublished | ToolTeamStateChanged, Field(discriminator="kind")]


class CatalogPage(Out):
    items: list[CatalogEvent]
    # The last module id of this page, to pass as `after` for the next; null on the last page.
    next_cursor: str | None


def catalog_events(agg: Aggregate, titles: TitleOf | None = None) -> list[CatalogEvent]:
    """A module as it stands, as the events that report it, titled as `report_module` titles them."""
    tenant, revision = str(agg["tenant_id"]), int(agg["revision"])
    module = ToolPublished(**catalog_of(agg, titles=titles).model_dump()).fitted(revision)
    owner = agg.get("team_id")
    out = [CatalogEvent(name=module.kind, tenant_id=tenant, team_id=owner, revision=revision, payload=module)]
    for team, state in sorted(team_grants(agg).items()):
        out.append(CatalogEvent(name=state.kind, tenant_id=tenant, team_id=team, revision=revision, payload=state))
    return out


class ToolCatalog(ModuleStore):
    async def page(self, tenant_id: str, *, after: str | None, limit: int) -> CatalogPage:
        """Up to `limit` modules of the tenant past `after` by id, every team's, as their events."""
        t = tool_modules.c
        where = [t.tenant_id == tenant_id, any_team(tool_modules, RESYNC), *([t.id > after] if after else [])]
        async with self.tx() as c:
            q = tool_modules.select().where(*where).order_by(t.id).limit(limit + 1)
            rows = list((await c.execute(q)).mappings())
            more, rows = len(rows) > limit, rows[:limit]
            kids = await self._children(c, tenant_id, [str(r["id"]) for r in rows])
        items = [e for r in rows for e in catalog_events(self._of(r, kids[str(r["id"])]), self.titles)]
        return CatalogPage(items=items, next_cursor=str(rows[-1]["id"]) if more else None)
