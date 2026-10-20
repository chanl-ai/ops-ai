"""A team's sending policy and the gateway's judgements against it (c-300).

The policy is the team's own written rules for what may leave (a reply, an outside call), kept as versions: a save adds
the next one and the newest is the one writes are judged against. A judgement is kept by the payload's input hash and
the policy version it was made against, so a retried or replayed write is judged once, and a new policy version
judges again; judgements against an older version are deleted when a new one is saved, and any past KEEP.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from ops_service_kit.ids import now_iso
from ops_store import Guarantee

from .modules import metadata

# How long a judgement is kept for the same payload under the same policy version.
KEEP = timedelta(days=30)

send_policies = sa.Table(
    "send_policies",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("saved_by", sa.String(320), nullable=False),
    sa.Column("saved_at", sa.String(32), nullable=False),
)

send_checks = sa.Table(
    "send_checks",
    metadata,
    sa.Column("tenant_id", sa.String(64), primary_key=True),
    sa.Column("team_id", sa.String(64), primary_key=True),
    sa.Column("input_hash", sa.String(80), primary_key=True),
    sa.Column("policy_version", sa.Integer, primary_key=True),
    sa.Column("ok", sa.Boolean, nullable=False),
    sa.Column("reason", sa.Text, nullable=False),
    sa.Column("checked_at", sa.String(32), nullable=False),
)


class SendPolicies:
    # A version is a primary key, so two saves at once cannot both take the next number (CAS); a judgement is kept
    # with one upsert that keeps the first (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    async def current(self, tenant_id: str, team_id: str) -> dict[str, Any] | None:
        t = send_policies
        q = sa.select(t).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id).order_by(t.c.version.desc()).limit(1)
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def save(self, tenant_id: str, team_id: str, text: str, *, by: str) -> dict[str, Any]:
        t = send_policies
        async with self.engine.begin() as c:
            newest = (
                await c.execute(
                    sa.select(sa.func.max(t.c.version)).where(t.c.tenant_id == tenant_id, t.c.team_id == team_id)
                )
            ).scalar()
            row = {
                "tenant_id": tenant_id,
                "team_id": team_id,
                "version": int(newest or 0) + 1,
                "text": text,
                "saved_by": by,
                "saved_at": now_iso(),
            }
            await c.execute(t.insert().values(**row))
            # Judgements are read against the newest version only, so those against older ones can never be read again.
            j = send_checks
            await c.execute(
                j.delete().where(
                    j.c.tenant_id == tenant_id, j.c.team_id == team_id, j.c.policy_version < row["version"]
                )
            )
        return row

    async def judged(self, tenant_id: str, team_id: str, input_hash: str, version: int) -> dict[str, Any] | None:
        t = send_checks
        q = sa.select(t.c.ok, t.c.reason).where(
            t.c.tenant_id == tenant_id,
            t.c.team_id == team_id,
            t.c.input_hash == input_hash,
            t.c.policy_version == version,
        )
        async with self.engine.connect() as c:
            row = (await c.execute(q)).mappings().first()
        return dict(row) if row else None

    async def keep(self, tenant_id: str, team_id: str, input_hash: str, version: int, *, ok: bool, reason: str) -> None:
        values = {
            "tenant_id": tenant_id,
            "team_id": team_id,
            "input_hash": input_hash,
            "policy_version": version,
            "ok": ok,
            "reason": reason,
            "checked_at": now_iso(),
        }
        cutoff = (datetime.now(UTC) - KEEP).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        j = send_checks
        async with self.engine.begin() as c:
            await c.execute(insert(j).values(**values).on_conflict_do_nothing())
            # A judgement is a cache: past KEEP the same payload is judged again rather than kept for ever.
            await c.execute(
                j.delete().where(j.c.tenant_id == tenant_id, j.c.team_id == team_id, j.c.checked_at < cutoff)
            )
