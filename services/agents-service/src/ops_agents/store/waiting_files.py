"""The files of a group whose Ready when has not passed: held per workflow, one row per file version (its item key,
as a batch row would carry it), until a check finds the group ready and takes them into the group's batch.

Retention (90 days for a group that never becomes ready) is not enforced yet: the sweep that deletes old rows comes
with the notifications sweep, which reads past row security and so joins the register in test_tenancy.py."""

from __future__ import annotations

from typing import ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Json, Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee
from ops_store.rows import rows
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.team_scope import team_visible

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

batch_waiting_files = sa.Table(
    "batch_waiting_files",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True, default=current_tenant),
    sa.Column("workflow_id", sa.String(200), primary_key=True),
    sa.Column("item_key", sa.String(96), primary_key=True),
    sa.Column("team_id", sa.String(64), nullable=False),
    sa.Column("group_key", sa.String(96), nullable=False),
    sa.Column("group_name", sa.String(300), nullable=False),
    sa.Column("input", sa.JSON, nullable=False),
    sa.Column("held_at", sa.String(32), nullable=False),
    sa.Index("ix_batch_waiting_group", "tenant_id", "workflow_id", "group_key"),
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class WaitingGroup(Out):
    """One group still waiting: its name, how many files it holds, and since when."""

    group_key: str
    group_name: str
    held: int
    since: str


class WaitingFile(Out):
    item_key: str
    input: Json


class WaitingFiles(RuntimeStore):
    requires: ClassVar[frozenset[Guarantee]] = frozenset()

    async def hold(self, *, team_id: str, workflow_id: str, group_key: str, group_name: str, files: list[Json]) -> int:
        """Holds `files` (`{itemKey, input}`) for the group; a file version already held is not held twice. Answers
        the number newly held."""
        w = batch_waiting_files
        keys = [str(f["itemKey"]) for f in files]
        async with self.tx() as c:
            held: set[str] = set(
                (await c.execute(sa.select(w.c.item_key).where(
                    w.c.tenant_id == current_tenant(), w.c.workflow_id == workflow_id, w.c.item_key.in_(keys)
                ))).scalars()
            ) if keys else set()  # fmt: skip
            fresh = [f for f in files if str(f["itemKey"]) not in held]
            if fresh:
                at = now_iso()
                await c.execute(
                    w.insert(),
                    [
                        {
                            "workflow_id": workflow_id, "item_key": str(f["itemKey"]), "team_id": team_id,
                            "group_key": group_key, "group_name": group_name, "input": f["input"], "held_at": at,
                        }
                        for f in fresh
                    ],
                )  # fmt: skip
        return len(fresh)

    async def held(self, workflow_id: str, limit: int = 200) -> list[WaitingGroup]:
        """The workflow's waiting groups, oldest first, at most `limit`."""
        w = batch_waiting_files
        since = sa.func.min(w.c.held_at)
        q = (
            sa.select(w.c.group_key, sa.func.max(w.c.group_name).label("group_name"),
                      sa.func.count().label("held"), since.label("since"))
            .where(w.c.tenant_id == current_tenant(), w.c.workflow_id == workflow_id, team_visible(w))
            .group_by(w.c.group_key)
            .order_by(since, w.c.group_key)
            .limit(limit)
        )  # fmt: skip
        async with self.tx() as c:
            return await rows(c, q, WaitingGroup)

    async def files(self, workflow_id: str, group_key: str) -> list[WaitingFile]:
        """The files a group holds, oldest first, without taking them."""
        w = batch_waiting_files
        q = (
            sa.select(w.c.item_key, w.c.input)
            .where(w.c.tenant_id == current_tenant(), w.c.workflow_id == workflow_id, w.c.group_key == group_key,
                   team_visible(w))
            .order_by(w.c.held_at, w.c.item_key)
        )  # fmt: skip
        async with self.tx() as c:
            return await rows(c, q, WaitingFile)

    async def take(self, workflow_id: str, group_key: str) -> list[WaitingFile]:
        """The files a group holds, removed in the same transaction, so two checks cannot both take them."""
        w = batch_waiting_files
        mine = (w.c.tenant_id == current_tenant(), w.c.workflow_id == workflow_id, w.c.group_key == group_key)
        async with self.tx() as c:
            taken = await rows(c, sa.select(w.c.item_key, w.c.input).where(*mine).order_by(w.c.held_at, w.c.item_key),
                               WaitingFile)  # fmt: skip
            if taken:
                keys = [t.item_key for t in taken]
                await c.execute(sa.delete(w).where(*mine, w.c.item_key.in_(keys)))
        return taken
