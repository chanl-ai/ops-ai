"""What the start-up hand-over of reviews reads and marks (c-163, c-222, `modules.review_handoff`): the modules' teams,
the versions waiting for a review Reviews has not opened, and open tool access requests."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_store.outbox import add as add_event
from ops_store.team_scope import any_team

from .modules import module_approvals, module_versions, service_outbox, tool_modules


class ReviewHandoffs:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def pending(self) -> tuple[dict[tuple[str, str], Any], list[dict[str, Any]]]:
        """Every module's name and team by (tenant, id), and the versions in review that carry a request id."""
        async with self.engine.connect() as c:
            modules = {
                (r.tenant_id, r.id): r
                for r in await c.execute(
                    sa.select(
                        tool_modules.c.tenant_id, tool_modules.c.id, tool_modules.c.display_name, tool_modules.c.team_id
                    ).where(any_team(tool_modules, "the start-up hand-over reads every tenant's modules"))
                )
            }
            waiting = [
                dict(r)
                for r in (
                    await c.execute(
                        sa.select(module_versions).where(
                            module_versions.c.status == "in_review", module_versions.c.review_id.is_not(None)
                        )
                    )
                ).mappings()
            ]
        return modules, waiting

    async def opened(self, version: dict[str, Any], review_id: str) -> None:
        """A seeded waiting version Reviews has opened: it takes the request id Reviews named."""
        async with self.engine.begin() as c:
            await c.execute(
                module_versions.update()
                .where(
                    module_versions.c.tenant_id == version["tenant_id"],
                    module_versions.c.module_id == version["module_id"],
                    module_versions.c.version == version["version"],
                    module_versions.c.review_id == version["review_id"],
                )
                .values(review_id=review_id)
            )

    async def open_access(self) -> list[dict[str, Any]]:
        """Workflow requests for a module's operations still open and not yet a system workflow run (c-257): none
        recorded, or a review opened in Reviews before requests ran as workflows (TAR-)."""
        a = module_approvals
        async with self.engine.connect() as c:
            q = sa.select(a).where(
                a.c.status == "requested", sa.or_(a.c.review_id.is_(None), a.c.review_id.startswith("TAR-"))
            )
            return [dict(r) for r in (await c.execute(q)).mappings()]

    async def start_access_run(self, row: dict[str, Any], *, event: dict[str, Any]) -> None:
        """An open request handed to its system workflow: its event and its run key commit together, so it is asked
        once, and a copy that runs again finds nothing left to hand over."""
        a = module_approvals
        async with self.engine.begin() as c:
            done = await c.execute(
                a.update()
                .where(
                    a.c.tenant_id == row["tenant_id"],
                    a.c.module_id == row["module_id"],
                    a.c.id == row["id"],
                    a.c.review_id.is_not_distinct_from(row["review_id"]),
                )
                .values(review_id=f"{event['name']}:{row['id']}", decider_team=event["team_id"])
            )
            if done.rowcount:
                await add_event(c, service_outbox, **event)
