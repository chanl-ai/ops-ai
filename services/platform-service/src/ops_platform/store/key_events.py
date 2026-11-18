"""`api_key.changed` for every API key write, in the transaction that makes it (`ops_store.outbox.add`), so
agents-service's copy of the keys (its Channels list) hears each change once the write commits and never one that
rolled back.

Each write raises the key's `revision`, so a copy keeps the newest state whatever order the relay delivers in. The event
carries what `GET /v1/api-key-summaries` lists of the key, never its secret or hash; a key's last use is not an event
(it changes on every call) and reaches the copy through that list. A purge reports each key it deletes, `deleted`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from ops_store.dialect import locked
from ops_store.outbox import ApiKeyChanged, Event
from ops_store.outbox import add as add_event

from .tables import api_keys, platform_outbox

API_KEY_CHANGED: str = ApiKeyChanged.model_fields["kind"].default
# Ids per statement, under SQL Server's 2100 parameters, so closing a large workspace still writes in one transaction.
_CHUNK = 500
Status = Literal["active", "disabled", "revoked"]


def status_of(revoked_at: str | None, disabled_at: str | None) -> Status:
    """Whether a key works, as every reply and event states it: revoked wins over disabled."""
    return "revoked" if revoked_at else "disabled" if disabled_at else "active"


async def announce(c: AsyncConnection, ids: Sequence[str], *, deleted: bool = False) -> None:
    """One event per key, at the revision the caller's write left it at, from the row as this transaction sees it;
    `deleted` when the caller removes the rows next, in the same transaction."""
    k = api_keys
    cols = (k.c.id, k.c.tenant_id, k.c.team_id, k.c.name, k.c.prefix, k.c.revoked_at, k.c.disabled_at, k.c.revision)
    cols += (k.c.target_kind, k.c.target_id, k.c.target_version, k.c.created_at, k.c.last_used_at, k.c.expires_at)
    for i in range(0, len(ids), _CHUNK):
        found = (await c.execute(sa.select(*cols).where(k.c.id.in_(ids[i : i + _CHUNK])).order_by(k.c.id))).mappings()
        for r in found.all():
            payload = ApiKeyChanged(
                id=r["id"],
                name=r["name"],
                prefix=r["prefix"],
                status=status_of(r["revoked_at"], r["disabled_at"]),
                target_kind=r["target_kind"],
                target_id=r["target_id"],
                target_version=r["target_version"],
                created_at=r["created_at"],
                last_used_at=r["last_used_at"],
                expires_at=r["expires_at"],
                deleted=deleted,
            )
            event = Event(
                name=API_KEY_CHANGED,
                tenant_id=r["tenant_id"],
                team_id=r["team_id"],
                revision=int(r["revision"]),
                payload=payload,
            )
            await add_event(c, platform_outbox, event)


async def _lock_ids(c: AsyncConnection, where: sa.ColumnElement[bool]) -> list[str]:
    q = locked(sa.select(api_keys.c.id).where(where).order_by(api_keys.c.id), api_keys)
    return [str(i) for i in (await c.execute(q)).scalars().all()]


async def _raise_revisions(c: AsyncConnection, ids: Sequence[str], values: Mapping[str, str | None]) -> None:
    for i in range(0, len(ids), _CHUNK):
        await c.execute(
            api_keys.update()
            .where(api_keys.c.id.in_(ids[i : i + _CHUNK]))
            .values(**values, revision=api_keys.c.revision + 1)
        )


async def change_keys(c: AsyncConnection, where: sa.ColumnElement[bool], values: Mapping[str, str | None]) -> list[str]:
    """Sets `values` (when a key was revoked or disabled, or None) on the keys `where` selects, raises each one's
    revision and announces it; returns their ids. The rows are locked first, so two writes to one key take its
    revisions in turn."""
    ids = await _lock_ids(c, where)
    await _raise_revisions(c, ids, values)
    await announce(c, ids)
    return ids


async def delete_keys(c: AsyncConnection, where: sa.ColumnElement[bool]) -> list[str]:
    """Deletes the keys `where` selects and announces each one deleted, one revision above its last event, so the copy
    drops them now rather than at a resync (which runs only for tenants that publish agents); returns their ids."""
    ids = await _lock_ids(c, where)
    await _raise_revisions(c, ids, {})
    await announce(c, ids, deleted=True)
    for i in range(0, len(ids), _CHUNK):
        await c.execute(api_keys.delete().where(api_keys.c.id.in_(ids[i : i + _CHUNK])))
    return ids
