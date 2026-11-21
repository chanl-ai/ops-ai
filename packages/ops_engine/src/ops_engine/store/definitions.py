"""Stored v2 definitions: one row per version, immutable once written except for its stage (draft, live, paused,
superseded), which only the transitions below change."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, ClassVar, TypedDict, cast

import sqlalchemy as sa
from pydantic import BeforeValidator, JsonValue

from ops_service_kit.http import Json, JsonList, Out
from ops_service_kit.narrow import json_object
from ops_store import Guarantee
from ops_store.dialect import locked
from ops_store.rows import one, rows
from ops_store.team_scope import team_visible

from .tables import engine_definitions, engine_runs, engine_steps, engine_working_copies
from .tx import LIVE_WORKFLOWS, Transactions


class WorkflowOwnedError(PermissionError):
    """The workflow id belongs to another team; a team cannot publish a version over it."""


class StaleWorkingCopy(Exception):
    """A working copy save named a copy that is no longer the newest: the newest is `version` and `digest`, saved by
    `saved_by` at `saved_at`. Raised inside the write's transaction, so nothing was written."""

    def __init__(self, version: int, digest: str, saved_by: str, saved_at: str) -> None:
        super().__init__(f"the newest copy is version {version} {digest[:12]}")
        self.version, self.digest, self.saved_by, self.saved_at = version, digest, saved_by, saved_at


# The stages that serve the workflow: at most one version is in one of them.
CURRENT = ("live", "paused")
# The node type whose step opens a Human Task (node_types.py, executor review.open: the only effects="human" type).
HUMAN_REVIEW = "ops.flow.humanReview"


def _seen_by(team: str | None) -> sa.ColumnElement[bool]:
    """Rows `team` may see: its own and the unowned ones; every row when no team is selected (the loops, dev)."""
    t = engine_definitions
    return sa.true() if team is None else sa.or_(t.c.team_id == team, t.c.team_id.is_(None))


class ListColumns(TypedDict):
    """What the Workflows list reads of a definition, stored on each version (`node_types.list_columns`)."""

    description: str
    trigger: str
    startable: bool
    takes_files: bool
    # The mailbox its Email received trigger names, if it has one: the Channels list joins its mailboxes on it.
    mailbox: str | None


# A definition's list columns: `node_types.list_columns` with the host's type registry, which this package's store may
# not import.
Describe = Callable[[JsonValue], ListColumns]


def unlisted(definition: JsonValue) -> ListColumns:
    """The list columns of a store given no `describe` (tests that store a definition with no type registry): the
    description and, as the trigger text, the description; started by hand by nobody."""
    description = str(definition.get("description") or "") if isinstance(definition, dict) else ""
    return {
        "description": description,
        "trigger": description,
        "startable": False,
        "takes_files": False,
        "mailbox": watched_mailbox(definition),
    }


EMAIL_TRIGGER = "ops.trigger.email"
MAILBOX_MAX = 320


def watched_mailbox(definition: JsonValue) -> str | None:
    """The address its Email received trigger names, if it has one; needs no type registry."""
    raw = definition.get("nodes") if isinstance(definition, dict) else None
    for node in raw if isinstance(raw, list) else []:
        if isinstance(node, dict) and node.get("type") == EMAIL_TRIGGER:
            params = node.get("parameters")
            found = params.get("mailbox") if isinstance(params, dict) else None
            # engine_definitions.mailbox holds an address; anything else names no mailbox that could exist.
            return found if isinstance(found, str) and 0 < len(found) <= MAILBOX_MAX else None
    return None


# A stored definition that is not an object reads as {}, as its readers read it with `or {}`: one odd row must not fail
# a list or the mailbox listener for every team. An object is kept as stored, so its digest is unchanged.
StoredDefinition = Annotated[Json, BeforeValidator(json_object)]


class DefinitionRow(Out):
    """One stored version of a workflow, as `engine_definitions` holds it. The definition stays the JSON it was
    stored as: its digest hashes that JSON, so it is never rebuilt from a model here."""

    tenant_id: str
    workflow_id: str
    version: int
    digest: str
    name: str
    definition: StoredDefinition
    created_at: str
    created_by: str
    team_id: str | None = None
    stage: str
    archived_at: str | None = None
    archived_by: str | None = None
    description: str
    trigger: str
    startable: bool
    takes_files: bool
    mailbox: str | None = None


class DefinitionVersion(Out):
    """One version in a workflow's history."""

    version: int
    digest: str
    created_at: str
    created_by: str
    stage: str


class DefinitionSummary(Out):
    """A workflow's latest version with the version that serves it and its run counts (DefinitionStore.summaries)."""

    workflow_id: str
    name: str
    version: int
    digest: str
    definition: StoredDefinition
    created_at: str
    created_by: str
    team_id: str | None = None
    stage: str
    archived_at: str | None = None
    # The version that serves it and that version's stage; None before the first approval.
    current_version: int | None = None
    current_stage: str | None = None
    runs: int
    recent: int
    reviewed: int
    open_reviews: int


class WorkingCopy(Out):
    """A workflow's one mutable copy, as the editor last saved it (`engine_working_copies`)."""

    tenant_id: str
    workflow_id: str
    team_id: str | None = None
    definition: StoredDefinition
    digest: str
    base_version: int
    checks: JsonList
    updated_at: str
    updated_by: str


def _newest_locked(tenant: str, workflow_id: str) -> sa.Select[Any]:
    """The workflow's newest version row, a few columns, locked: what an autosave and a publish both hold, by one
    statement, so each waits on the other on PostgreSQL and SQL Server alike."""
    t = engine_definitions
    query = cast(sa.Select[Any], sa.select(t.c.version, t.c.digest, t.c.created_by, t.c.created_at, t.c.team_id))
    return locked(
        query.where(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id).order_by(t.c.version.desc()).limit(1), t
    )


class DefinitionStore:
    # A version is the next number for its workflow unless its digest is stored already; the primary key on the
    # number keeps two saves from taking one (CAS), and the workflow's rows are locked while it is chosen.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.TRANSACTION, Guarantee.CAS})

    def __init__(self, tx: Transactions, describe: Describe = unlisted) -> None:
        self.tx = tx
        self.describe = describe

    async def publish(
        self,
        workflow_id: str,
        *,
        name: str,
        definition: Json,
        digest: str,
        now: str,
        by: str,
        team: str | None = None,
        stage: str = "draft",
        reopen: bool = False,
    ) -> tuple[int, bool]:
        """Stores the next version at `stage` (a save is a draft; only the dev seed stores one live, through
        `go_live`) with its list columns (`describe`) in the same statement; the same definition again returns its
        version. With `reopen`, a definition stored before only at a superseded version is stored again as the next
        version, so a restored older version can be published. Returns (version, created)."""
        t = engine_definitions
        listed = self.describe(definition)
        async with self.tx.tenant_tx() as c:
            # The id's existing versions, locked: a workflow id belongs to the team that first published it.
            rows = (await c.execute(locked(sa.select(t.c.team_id).where(t.c.workflow_id == workflow_id), t))).all()
            # The autosave's lock as well: on SQL Server a lock read through another index does not block it.
            await c.execute(_newest_locked(self.tx.tenant(), workflow_id))
            owners = {r.team_id for r in rows}
            if owners and owners != {team} and not (team is None and owners == {None}):
                raise WorkflowOwnedError(f"workflow id {workflow_id} belongs to another team")
            same = (
                await c.execute(
                    sa.select(t.c.version, t.c.stage)
                    .where(t.c.workflow_id == workflow_id, t.c.digest == digest)
                    .order_by(t.c.version.desc())
                )
            ).first()
            if same is not None and not (reopen and same.stage == "superseded"):
                return int(same.version), False
            latest = (
                await c.execute(sa.select(sa.func.max(t.c.version)).where(t.c.workflow_id == workflow_id))
            ).scalar()
            version = int(latest or 0) + 1
            await c.execute(
                t.insert().values(
                    tenant_id=self.tx.tenant(),
                    workflow_id=workflow_id,
                    version=version,
                    digest=digest,
                    name=name,
                    definition=definition,
                    created_at=now,
                    created_by=by,
                    team_id=team,
                    stage=stage,
                    **listed,
                )
            )
            return version, True

    async def working_copy(self, workflow_id: str, *, team: str | None = None) -> WorkingCopy | None:
        """The workflow's working copy; None when it has none or `team` may not see it."""
        w = engine_working_copies
        seen = sa.true() if team is None else sa.or_(w.c.team_id == team, w.c.team_id.is_(None))
        q = w.select().where(w.c.tenant_id == self.tx.tenant(), w.c.workflow_id == workflow_id, seen, team_visible(w))
        async with self.tx.tenant_tx() as c:
            return await one(c, q, WorkingCopy)

    async def put_working_copy(
        self,
        workflow_id: str,
        *,
        definition: Json,
        digest: str,
        checks: list[Json],
        base: tuple[int, str],
        now: str,
        by: str,
        replaces: str | None = None,
    ) -> WorkingCopy:
        """Stores `definition` as the working copy, whatever its checks say, when `base` (the version and digest the
        save was made on) names the newest copy: the working copy when there is one made on the newest version, the
        newest version otherwise. Another person's copy made on an older version is replaced only by a save whose
        `replaces` is that copy's digest. The newest version and the copy are locked first, so two saves made on one
        copy cannot both pass the compare. Raises StaleWorkingCopy when `base` is older (naming that other person's copy
        when it is theirs), and LookupError when the workflow has no version."""
        w = engine_working_copies
        tenant = self.tx.tenant()
        mine = sa.and_(w.c.tenant_id == tenant, w.c.workflow_id == workflow_id, team_visible(w))
        async with self.tx.tenant_tx() as c:
            # The newest row alone, without its definition; a publish takes the same lock, so each waits on the other.
            newest = (await c.execute(_newest_locked(tenant, workflow_id))).first()
            if newest is None:
                raise LookupError(f"workflow {workflow_id} has no version")
            held = (await c.execute(locked(w.select().where(mine), w))).first()
            # A copy made on an older version than the newest (one saved through the API or CLI since) is outdated:
            # the newest version is the base, so the editor is told and its next save is made on that version.
            current = held if held is not None and int(held.base_version) >= int(newest.version) else None
            if current is not None:
                token = (
                    int(current.base_version),
                    str(current.digest),
                    str(current.updated_by),
                    str(current.updated_at),
                )
            else:
                token = (int(newest.version), str(newest.digest), str(newest.created_by), str(newest.created_at))
            if base != token[:2]:
                raise StaleWorkingCopy(*token)
            outdated = held if held is not None and current is None else None
            # Another person's outdated copy holds their unpublished change: it is replaced only by a save naming it
            # (`replaces`, its digest), so starting from the newest version never drops it unseen.
            if outdated is not None and str(outdated.updated_by) != by and replaces != str(outdated.digest):
                raise StaleWorkingCopy(
                    int(outdated.base_version), str(outdated.digest), str(outdated.updated_by), str(outdated.updated_at)
                )
            values = {"definition": definition, "digest": digest, "checks": checks, "updated_at": now, "updated_by": by}
            if held is not None:
                # The compare is part of the write as well, so a writer that skipped the lock still cannot win.
                await c.execute(
                    w.update().where(mine, w.c.digest == held.digest).values(**values, base_version=token[0])
                )
            else:
                await c.execute(
                    w.insert().values(
                        tenant_id=tenant,
                        workflow_id=workflow_id,
                        team_id=newest.team_id,
                        base_version=token[0],
                        **values,
                    )
                )
            saved = await one(c, w.select().where(mine), WorkingCopy)
        if saved is None:
            raise LookupError(f"workflow {workflow_id} lost its working copy while saving")
        return saved

    async def drop_working_copy(self, workflow_id: str, *, digest: str | None = None) -> bool:
        """Removes the working copy; with `digest`, only while it is still that copy, so a save made after a version
        was taken from it is kept. Returns whether a row went."""
        w = engine_working_copies
        where = sa.and_(w.c.tenant_id == self.tx.tenant(), w.c.workflow_id == workflow_id, team_visible(w))
        if digest is not None:
            where = sa.and_(where, w.c.digest == digest)
        async with self.tx.tenant_tx() as c:
            return bool((await c.execute(w.delete().where(where))).rowcount)

    async def rebase_working_copy(self, workflow_id: str, version: int) -> None:
        """Moves the working copy onto `version`: a save made while a version was taken from an earlier copy stays a
        change waiting on that version."""
        w = engine_working_copies
        where = sa.and_(
            w.c.tenant_id == self.tx.tenant(),
            w.c.workflow_id == workflow_id,
            w.c.base_version < version,
            team_visible(w),
        )
        async with self.tx.tenant_tx() as c:
            await c.execute(w.update().where(where).values(base_version=version))

    async def serving(self, workflow_id: str, *, team: str | None = None) -> DefinitionRow | None:
        """The version that serves the workflow, live or paused; None when no version has been approved."""
        t = engine_definitions
        q = t.select().where(
            t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant(), t.c.stage.in_(CURRENT), _seen_by(team)
        )
        async with self.tx.tenant_tx() as c:
            return await one(c, q.order_by(t.c.version.desc()).limit(1), DefinitionRow)

    async def current(self, workflow_id: str, *, team: str | None = None) -> dict[str, Any] | None:
        """serving() as a mapping; only tests still read it, and it goes once they read serving()."""
        found = await self.serving(workflow_id, team=team)
        return found.model_dump() if found else None

    async def currents(self, workflow_ids: set[str]) -> dict[str, DefinitionRow]:
        """serving() for each of these workflows in one query, so a list of many runs reads the versions that serve
        their workflows together; a workflow with no approved version is left out."""
        if not workflow_ids:
            return {}
        t = engine_definitions
        q = t.select().where(
            t.c.workflow_id.in_(sorted(workflow_ids)), t.c.tenant_id == self.tx.tenant(), t.c.stage.in_(CURRENT)
        )
        async with self.tx.tenant_tx() as c:
            found = await rows(c, q.order_by(t.c.version), DefinitionRow)
        # Ascending, so each workflow keeps its highest version, as serving() orders and takes the first.
        return {r.workflow_id: r for r in found}

    async def live(self, workflow_id: str, *, team: str | None = None) -> DefinitionRow | None:
        """The version a live run starts on; None when there is none or the workflow is paused."""
        row = await self.serving(workflow_id, team=team)
        return row if row and row.stage == "live" else None

    async def live_everywhere(self) -> list[DefinitionRow]:
        """Every live version in every tenant, for a loop that serves live workflows from outside any request (the
        mailbox listener). Paused versions are left out: they start no runs."""
        t = engine_definitions
        async with self.tx.system_tx(LIVE_WORKFLOWS) as c:
            live = sa.and_(t.c.stage == "live", t.c.archived_at.is_(None))
            return await rows(c, t.select().where(live).order_by(t.c.tenant_id, t.c.workflow_id), DefinitionRow)

    async def go_live(self, workflow_id: str, version: int) -> str:
        """Makes `version` the one that serves the workflow and supersedes the one before, in one transaction. A
        paused workflow stays paused on the new version. Returns the version's stage; LookupError when it is gone."""
        t = engine_definitions
        tenant = self.tx.tenant()
        mine = sa.and_(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id)
        async with self.tx.tenant_tx() as c:
            rows = (
                await c.execute(locked(cast(sa.Select[Any], sa.select(t.c.version, t.c.stage).where(mine)), t))
            ).all()
            if version not in {r.version for r in rows}:
                raise LookupError(f"{workflow_id} version {version} no longer exists")
            stage = "paused" if any(r.stage == "paused" for r in rows) else "live"
            others = sa.and_(mine, t.c.version != version, t.c.stage.in_(CURRENT))
            await c.execute(t.update().where(others).values(stage="superseded"))
            await c.execute(t.update().where(mine, t.c.version == version).values(stage=stage))
        return stage

    async def set_paused(self, workflow_id: str, paused: bool, *, team: str | None = None) -> DefinitionRow | None:
        """Pauses or resumes the version that serves the workflow; None when it has none. Runs in flight keep going:
        only new live starts are refused."""
        t = engine_definitions
        where = sa.and_(
            t.c.tenant_id == self.tx.tenant(), t.c.workflow_id == workflow_id, t.c.stage.in_(CURRENT), _seen_by(team)
        )
        async with self.tx.tenant_tx() as c:
            await c.execute(t.update().where(where).values(stage="paused" if paused else "live"))
        return await self.serving(workflow_id, team=team)

    async def set_archived(
        self, workflow_id: str, archived: bool, *, by: str, now: str, team: str | None = None
    ) -> DefinitionRow | None:
        """Archives every version of the workflow, or restores it; its stages, versions and runs are kept, so
        a restored workflow serves as it did. Runs already started keep going. None when `team` sees no version."""
        t = engine_definitions
        where = sa.and_(t.c.tenant_id == self.tx.tenant(), t.c.workflow_id == workflow_id, _seen_by(team))
        values = {"archived_at": now, "archived_by": by} if archived else {"archived_at": None, "archived_by": None}
        async with self.tx.tenant_tx() as c:
            await c.execute(t.update().where(where).values(**values))
        return await self.row(workflow_id, team=team)

    async def row(
        self, workflow_id: str, version: int | None = None, *, team: str | None = None
    ) -> DefinitionRow | None:
        """One version, the latest when `version` is None; None when `team` may not see it."""
        t = engine_definitions
        q = t.select().where(t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant(), _seen_by(team))
        q = q.where(t.c.version == version) if version is not None else q.order_by(t.c.version.desc()).limit(1)
        async with self.tx.tenant_tx() as c:
            return await one(c, q, DefinitionRow)

    async def get(
        self, workflow_id: str, version: int | None = None, *, team: str | None = None
    ) -> dict[str, Any] | None:
        """row() as a mapping; only tests still read it, and it goes once they read row()."""
        found = await self.row(workflow_id, version, team=team)
        return found.model_dump() if found else None

    async def pinned(self, keys: set[tuple[str, int]]) -> dict[tuple[str, int], DefinitionRow]:
        """The versions at these (workflow_id, version) pairs in one query, so a page naming the workflows of many runs
        reads them together; a pair with no row is left out."""
        if not keys:
            return {}
        t = engine_definitions
        # An OR of pairs, not a tuple IN, which SQL Server refuses.
        pairs = sa.or_(*(sa.and_(t.c.workflow_id == w, t.c.version == v) for w, v in sorted(keys)))
        async with self.tx.tenant_tx() as c:
            found = await rows(c, t.select().where(t.c.tenant_id == self.tx.tenant(), pairs), DefinitionRow)
        return {(r.workflow_id, r.version): r for r in found}

    async def versions(self, workflow_id: str) -> list[DefinitionVersion]:
        t = engine_definitions
        q = (
            sa.select(t.c.version, t.c.digest, t.c.created_at, t.c.created_by, t.c.stage)
            .where(t.c.workflow_id == workflow_id, t.c.tenant_id == self.tx.tenant())
            .order_by(t.c.version)
        )
        async with self.tx.tenant_tx() as c:
            return await rows(c, q, DefinitionVersion)

    async def summaries(self, since: str | None = None, *, team: str | None = None) -> list[DefinitionSummary]:
        """Each workflow's latest version (name, version, digest, definition, stage, when and by whom), the version
        that serves it with its stage (`current_version`, `current_stage`; None before the first approval), how many
        runs it has had on any version, and how many started at or after `since` (an ISO time; none when left out),
        how many of those opened a Human Task (`reviewed`), and how many Human Tasks are open now (`open_reviews`);
        the caller filters, sorts and pages."""
        t, r = engine_definitions, engine_runs
        tenant = self.tx.tenant()
        latest = (
            sa.select(t.c.workflow_id, sa.func.max(t.c.version).label("version"))
            .where(t.c.tenant_id == tenant, _seen_by(team))
            .group_by(t.c.workflow_id)
            .subquery()
        )
        # At most one version is live or paused, so max() of its stage is that stage.
        serving = (
            sa.select(
                t.c.workflow_id,
                sa.func.max(t.c.version).label("current_version"),
                sa.func.max(t.c.stage).label("current_stage"),
            )
            .where(t.c.tenant_id == tenant, t.c.stage.in_(CURRENT))
            .group_by(t.c.workflow_id)
            .subquery()
        )
        recent = sa.case((r.c.created_at >= since, 1), else_=0) if since else sa.literal(0)
        runs = (
            sa.select(r.c.workflow_id, sa.func.count().label("runs"), sa.func.sum(recent).label("recent"))
            .where(r.c.tenant_id == tenant)
            .group_by(r.c.workflow_id)
            .subquery()
        )
        # A Human Task is a journaled step of the Human review node type; a step that failed to open one has status
        # "error". A task is open while its step waits and its run still does (a cancelled run keeps its row).
        s = engine_steps
        reached = sa.case((r.c.created_at >= since, r.c.id)) if since else sa.null()
        is_open = sa.and_(s.c.status == "waiting", r.c.status == "waiting")
        humans = (
            sa.select(
                r.c.workflow_id,
                sa.func.count(sa.distinct(reached)).label("reviewed"),
                sa.func.sum(sa.case((is_open, 1), else_=0)).label("open_reviews"),
            )
            .join(s, sa.and_(s.c.run_id == r.c.id, s.c.tenant_id == r.c.tenant_id))
            .where(r.c.tenant_id == tenant, s.c.node_type == HUMAN_REVIEW, s.c.status != "error")
            .group_by(r.c.workflow_id)
            .subquery()
        )
        q = (
            sa.select(
                t.c.workflow_id,
                t.c.name,
                t.c.version,
                t.c.digest,
                t.c.definition,
                t.c.created_at,
                t.c.created_by,
                t.c.team_id,
                t.c.stage,
                t.c.archived_at,
                serving.c.current_version,
                serving.c.current_stage,
                # A workflow with no runs, or none that opened a Human Task, joins no row: it counts 0.
                sa.func.coalesce(runs.c.runs, 0).label("runs"),
                sa.func.coalesce(runs.c.recent, 0).label("recent"),
                sa.func.coalesce(humans.c.reviewed, 0).label("reviewed"),
                sa.func.coalesce(humans.c.open_reviews, 0).label("open_reviews"),
            )
            .join(latest, sa.and_(t.c.workflow_id == latest.c.workflow_id, t.c.version == latest.c.version))
            .outerjoin(serving, serving.c.workflow_id == t.c.workflow_id)
            .outerjoin(runs, runs.c.workflow_id == t.c.workflow_id)
            .outerjoin(humans, humans.c.workflow_id == t.c.workflow_id)
            .where(t.c.tenant_id == tenant, _seen_by(team))
        )
        async with self.tx.tenant_tx() as c:
            return await rows(c, q, DefinitionSummary)

    async def delete_draft(self, workflow_id: str, *, team: str | None = None) -> str:
        """Removes every version of a workflow that has never run. The versions are locked first, and a run start
        locks the version it pins (RunStore.create), so a start either commits before this reads the runs (and the
        workflow is kept) or finds its version gone. Returns "deleted", "missing" or "has_runs"."""
        t, r = engine_definitions, engine_runs
        tenant = self.tx.tenant()
        async with self.tx.tenant_tx() as c:
            held = await c.execute(
                locked(
                    sa.select(t.c.version).where(
                        t.c.tenant_id == tenant, t.c.workflow_id == workflow_id, _seen_by(team)
                    ),
                    t,
                )
            )
            if held.first() is None:
                return "missing"  # none, or another team's
            runs = (
                await c.execute(
                    sa.select(sa.func.count()).where(r.c.tenant_id == tenant, r.c.workflow_id == workflow_id)
                )
            ).scalar()
            if runs:
                return "has_runs"
            w = engine_working_copies
            await c.execute(w.delete().where(w.c.tenant_id == tenant, w.c.workflow_id == workflow_id))
            res = await c.execute(t.delete().where(t.c.tenant_id == tenant, t.c.workflow_id == workflow_id))
            return "deleted" if res.rowcount else "missing"
