"""This service's copy of platform-service's API keys (`ops_store.copies`), as the Channels list shows them: kept by
platform's `api_key.changed` events and repaired by a resync of `GET /v1/api-key-summaries` per tenant, so the list
pages, filters and counts API channels in SQL without asking platform-service per request.

- `api_key_copies`: one row per key, keyed by tenant, team and key id. Never the secret or its hash: `prefix` is the
  key's public id part. A revoked key keeps its row with that status, so a run it started keeps the key's name; the
  list leaves it out.

A copy answers what to show; whether a key may start anything is always decided by platform-service where it is used.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import ClassVar, Literal

import sqlalchemy as sa
from pydantic import JsonValue

from ops_service_kit.http import Out
from ops_store import Guarantee, background, copies
from ops_store.outbox import ApiKeyChanged, Event
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED

from .base import metadata
from .tenancy import RuntimeStore, current_tenant

API_KEY_CHANGED = ApiKeyChanged.model_fields["kind"].default
# The revision of a listed key whose summary carries none (a platform-service older than its `revision` field): a later
# event at any revision above it wins, and the next resync sets the row back to what platform lists.
LISTED_REVISION = 0

api_key_copies = copies.copy_table(
    metadata,
    "api_key_copies",
    sa.Column("name", sa.String(200), nullable=False),
    sa.Column("prefix", sa.String(64), nullable=False),
    sa.Column("status", sa.String(16), nullable=False),
    sa.Column("target_kind", sa.String(16), nullable=True),
    sa.Column("target_id", sa.String(64), nullable=True),
    sa.Column("target_version", sa.Integer, nullable=True),
    sa.Column("created_at", sa.String(40), nullable=False),
    sa.Column("last_used_at", sa.String(40), nullable=True),
    sa.Column("expires_at", sa.String(40), nullable=True),
    marking={**TENANT_SCOPED, **TEAM_OWNED},
)
# The Channels list reads one tenant's keys of the caller's teams, by name.
sa.Index("ix_api_key_copies_team_name", api_key_copies.c.tenant_id, api_key_copies.c.team_id, api_key_copies.c.name)

RESYNC_KEY = "api_key_copy_resync"
# The repair pass for an event the relay never delivered and for a key's last use, which is no event. A constant,
# not a setting, so it stays at a minute.
RESYNC_EVERY_S = 60.0
RESYNC = background.register(
    background.Process(
        RESYNC_KEY,
        "agents",
        "Copy of the API keys",
        "Reads platform-service's API keys for each workspace and repairs api_key_copies.",
        RESYNC_EVERY_S,
        "platform-service lists one workspace's keys, every team's; each workspace is applied as itself.",
    )
)


class KeyTarget(Out):
    kind: str
    id: str
    version: int | None = None


class KeySummary(Out):
    """One key of platform-service's `GET /v1/api-key-summaries` (its ApiKeySummary): what it serves and whether it
    works, never its creator or secret."""

    id: str
    name: str
    prefix: str
    status: Literal["active", "disabled", "revoked"]
    target: KeyTarget | None
    last_used_at: str | None
    expires_at: str | None
    created_at: str
    team_id: str
    # The key's revision, as its `api_key.changed` events carry it, so a resync never sets a row below an event.
    revision: int = LISTED_REVISION


def listed_event(summary: KeySummary, *, tenant_id: str) -> Event:
    """One listed key as the event that writes its copy row."""
    t = summary.target
    payload = ApiKeyChanged(
        id=summary.id,
        name=summary.name,
        prefix=summary.prefix,
        status=summary.status,
        target_kind=t.kind if t else None,
        target_id=t.id if t else None,
        target_version=t.version if t else None,
        created_at=summary.created_at,
        last_used_at=summary.last_used_at,
        expires_at=summary.expires_at,
    )
    return Event(
        name=API_KEY_CHANGED, tenant_id=tenant_id, team_id=summary.team_id, revision=summary.revision, payload=payload
    )


def wired_event(team_id: str, payload: Mapping[str, JsonValue], *, tenant_id: str) -> Event:
    """An `api_key.changed` as `POST /v1/platform-events` receives it: `ops_store.outbox.add` sends the payload with
    the event's revision inside it, and the tenant and team are the token's."""
    body = dict(payload)
    revision = body.pop("revision", LISTED_REVISION)
    return Event.model_validate(
        {"name": API_KEY_CHANGED, "tenantId": tenant_id, "teamId": team_id, "revision": revision, "payload": body}
    )


class ApiKeyCopies(RuntimeStore):
    # An event's guarded upsert (`copies.apply`, CAS) and a resync's guarded writes, each in one transaction.
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS, Guarantee.TRANSACTION})

    async def apply(self, events: Sequence[Event]) -> int:
        """Applies each event as the current tenant; an older or equal revision changes nothing."""
        async with self.tx() as c:
            for event in events:
                if event.tenant_id != current_tenant() or not isinstance(event.payload, ApiKeyChanged):
                    raise ValueError(f"{event.name} is not this tenant's API key event")
                await copies.apply(c, api_key_copies, event)
        return len(events)

    async def held(self) -> dict[copies.Key, copies.Held]:
        """The current tenant's rows, tombstones included, before platform-service is asked (`copies.reconcile`).
        Kept to the tenant here as well as by the row policy, since `reconcile` buries every held row the list lacks."""
        tenant = current_tenant()
        async with self.tx() as c:
            return {k: h for k, h in (await copies.held(c, api_key_copies)).items() if k[0] == tenant}

    async def reconcile(self, records: Sequence[Event], before: Mapping[copies.Key, copies.Held]) -> int:
        """Makes the current tenant's rows equal to platform's list; a row an event changed meanwhile is kept."""
        if any(r.tenant_id != current_tenant() for r in records):
            raise ValueError("a resync applies one tenant's keys")
        async with self.tx() as c:
            return await copies.reconcile(c, api_key_copies, records, before)
