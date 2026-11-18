"""A team's sending policy and the gateway's judgements against it.

The policy is the team's own written rules for what may leave (a reply, an outside call), kept as versions: a save adds
the next one and the newest is the one writes are judged against. A judgement is kept by the payload's input hash and
the policy version it was made against, so a retried or replayed write is judged once, and a new policy version
judges again; judgements against an older version are deleted when a new one is saved, and any past KEEP.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import ClassVar

import sqlalchemy as sa

from ops_service_kit.http import Out
from ops_service_kit.ids import now_iso
from ops_store import Guarantee, isolation
from ops_store.dialect import insert_ignore
from ops_store.rows import one
from ops_store.schema import TEAM_OWNED, TENANT_SCOPED
from ops_store.store import Store
from ops_store.team_scope import team_visible

from .modules import metadata
from .tenancy import ROLE

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
    info={**TENANT_SCOPED, **TEAM_OWNED},
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
    info={**TENANT_SCOPED, **TEAM_OWNED},
)


class SendPolicy(Out):
    """A team's sending policy at one version."""

    version: int
    text: str
    saved_by: str
    saved_at: str


class Judgement(Out):
    """A kept judgement of one payload against one policy version."""

    ok: bool
    reason: str


_POLICY = (send_policies.c.version, send_policies.c.text, send_policies.c.saved_by, send_policies.c.saved_at)


class SendPolicies(Store):
    # A version is a primary key, so two saves at once cannot both take the next number (CAS); a judgement is kept
    # with one insert that keeps the first (CAS).
    requires: ClassVar[frozenset[Guarantee]] = frozenset({Guarantee.CAS})
    role = ROLE

    async def current(self, tenant_id: str, team_id: str) -> SendPolicy | None:
        t = send_policies
        q = (
            sa.select(*_POLICY)
            .where(t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t))
            .order_by(t.c.version.desc())
            .limit(1)
        )
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return await one(c, q, SendPolicy)

    async def save(self, tenant_id: str, team_id: str, text: str, *, by: str) -> SendPolicy:
        t = send_policies
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                newest = (
                    await c.execute(
                        sa.select(sa.func.max(t.c.version)).where(
                            t.c.tenant_id == tenant_id, t.c.team_id == team_id, team_visible(t)
                        )
                    )
                ).scalar()
                saved = SendPolicy(version=int(newest or 0) + 1, text=text, saved_by=by, saved_at=now_iso())
                await c.execute(t.insert().values(tenant_id=tenant_id, team_id=team_id, **saved.model_dump()))
                # Judgements are read against the newest version only, so those against older ones are never read again.
                j = send_checks
                await c.execute(
                    j.delete().where(
                        j.c.tenant_id == tenant_id, j.c.team_id == team_id, j.c.policy_version < saved.version
                    )
                )
        return saved

    async def judged(self, tenant_id: str, team_id: str, input_hash: str, version: int) -> Judgement | None:
        t = send_checks
        q = sa.select(t.c.ok, t.c.reason).where(
            t.c.tenant_id == tenant_id,
            t.c.team_id == team_id,
            t.c.input_hash == input_hash,
            t.c.policy_version == version,
            team_visible(t),
        )
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                return await one(c, q, Judgement)

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
        with isolation.scope(tenant_id, team_id):
            async with self.tx() as c:
                await c.execute(
                    insert_ignore(c, j, values, keys=["tenant_id", "team_id", "input_hash", "policy_version"])
                )
                # A judgement is a cache: past KEEP the same payload is judged again rather than kept for ever.
                await c.execute(
                    j.delete().where(j.c.tenant_id == tenant_id, j.c.team_id == team_id, j.c.checked_at < cutoff)
                )
