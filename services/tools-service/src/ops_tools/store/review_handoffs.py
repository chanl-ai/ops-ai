"""What the start-up hand-over of reviews reads and marks (`modules.review_handoff`): the modules' teams,
the versions waiting for a review Reviews has not opened, and open tool access requests."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import sqlalchemy as sa
from pydantic import JsonValue

from ops_service_kit.http import Out
from ops_store import isolation
from ops_store.outbox import add as add_event
from ops_store.rows import rows
from ops_store.store import Store
from ops_store.team_scope import any_team

from .modules import module_approvals, module_versions, service_outbox, tool_modules
from .tenancy import ROLE, SYSTEM_ROLE

# Why the hand-over lists every tenant's modules, waiting versions and open requests: it runs once at start, before any
# tenant is known, and settles each item in that item's own tenant.
HANDOFF_LIST = "the start-up hand-over lists every tenant's waiting reviews and open access requests"
# Why one item is settled across its tenant's teams: the version or request is the module's, whichever team owns it.
HANDOFF_SETTLE = "the start-up hand-over settles one waiting review or access request in its own tenant"


class ModuleOwner(Out):
    """A module's name and the team that owns it."""

    tenant_id: str
    id: str
    display_name: str
    team_id: str | None


class WaitingVersion(Out):
    """A module version in review that carries a request id."""

    tenant_id: str
    module_id: str
    version: str
    review_id: str
    published_by: str


class OpenAccess(Out):
    """A workflow's open request for a module's operations, with what its event carries."""

    tenant_id: str
    module_id: str
    id: str
    review_id: str | None
    decider_team: str | None
    workflow_id: str
    workflow_name: str
    operations: list[JsonValue]
    environment: str
    expires_at: datetime | None
    justification: str
    requested_by: str
    requested_by_email: str | None


class ReviewHandoffs(Store):
    role = ROLE
    system_role = SYSTEM_ROLE

    async def pending(self) -> tuple[dict[tuple[str, str], ModuleOwner], list[WaitingVersion]]:
        """Every module's name and team by (tenant, id), and the versions in review that carry a request id."""
        m, v = tool_modules, module_versions
        async with self.system_tx(HANDOFF_LIST) as c:
            owners = await rows(
                c,
                sa.select(m.c.tenant_id, m.c.id, m.c.display_name, m.c.team_id).where(any_team(m, HANDOFF_LIST)),
                ModuleOwner,
            )
            waiting = await rows(
                c,
                sa.select(v.c.tenant_id, v.c.module_id, v.c.version, v.c.review_id, v.c.published_by).where(
                    v.c.status == "in_review", v.c.review_id.is_not(None)
                ),
                WaitingVersion,
            )
        return {(o.tenant_id, o.id): o for o in owners}, waiting

    async def opened(self, version: WaitingVersion, review_id: str) -> None:
        """A seeded waiting version Reviews has opened: it takes the request id Reviews named."""
        with isolation.tenant_wide(HANDOFF_SETTLE, tenant_id=version.tenant_id):
            async with self.tx() as c:
                await c.execute(
                    module_versions.update()
                    .where(
                        module_versions.c.tenant_id == version.tenant_id,
                        module_versions.c.module_id == version.module_id,
                        module_versions.c.version == version.version,
                        module_versions.c.review_id == version.review_id,
                    )
                    .values(review_id=review_id)
                )

    async def open_access(self) -> list[OpenAccess]:
        """Workflow requests for a module's operations still open and not yet a system workflow run: none
        recorded, or a review opened in Reviews before requests ran as workflows (TAR-)."""
        a = module_approvals
        cols = [a.c[name] for name in OpenAccess.model_fields]
        async with self.system_tx(HANDOFF_LIST) as c:
            q = sa.select(*cols).where(
                a.c.status == "requested", sa.or_(a.c.review_id.is_(None), a.c.review_id.startswith("TAR-"))
            )
            return await rows(c, q, OpenAccess)

    async def start_access_run(self, row: OpenAccess, *, event: dict[str, Any]) -> None:
        """An open request handed to its system workflow: its event and its run key commit together, so it is asked
        once, and a copy that runs again finds nothing left to hand over."""
        a = module_approvals
        with isolation.tenant_wide(HANDOFF_SETTLE, tenant_id=row.tenant_id):
            async with self.tx() as c:
                done = await c.execute(
                    a.update()
                    .where(
                        a.c.tenant_id == row.tenant_id,
                        a.c.module_id == row.module_id,
                        a.c.id == row.id,
                        a.c.review_id.is_not_distinct_from(row.review_id),
                    )
                    .values(review_id=f"{event['name']}:{row.id}", decider_team=event["team_id"])
                )
                if done.rowcount:
                    await add_event(c, service_outbox, **event)
