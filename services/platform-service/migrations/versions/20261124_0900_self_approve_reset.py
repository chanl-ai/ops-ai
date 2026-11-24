"""policies: store self-approval false at every tenant default and every team that stored a value

Approve own requests is a role cell from 1.2.0 (Approvals · decide, Admin only), and teams that turned self-approval
on are reset to Admin only (owner, 23 November). `requesterMayDecide` is no longer read by 1.2.0 code, but a rolled
back tools-service or console still reads it, so the value is stored false rather than deleted: a deleted value
would read 1.1.0's default, on, and give self-approval to everyone. Per tenant this stores false at the workspace `*`
entry (also for a tenant that stored nothing) and for each team that stored a value, drops the floor's self-approval
part (its app-change part stays), and writes one `policy.reset` audit entry per team reset and one per tenant
default, with actor `migration:<revision>`. A second run finds every value false and writes nothing. The downgrade
puts back each value from its audit entries.

Revision ID: 20261124_0900_self_approve_reset
Revises: 20261123_1200_self_approval_cell
"""

from __future__ import annotations

import json
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

from ops_service_kit.ids import new_id, now_iso

revision = "20261124_0900_self_approve_reset"
down_revision = "20261123_1200_self_approval_cell"
branch_labels = None
depends_on = None

ACTOR = f"migration:{revision}"
KEY = "requesterMayDecide"
FLOOR = "approvalsFloor"

audit_entries = sa.table(
    "audit_entries",
    sa.column("id", sa.String),
    sa.column("tenant_id", sa.String),
    sa.column("team_id", sa.String),
    sa.column("actor", sa.String),
    sa.column("action", sa.String),
    sa.column("target_kind", sa.String),
    sa.column("target_id", sa.String),
    sa.column("request_id", sa.String),
    sa.column("at", sa.String),
    sa.column("detail", sa.JSON),
)
policies = sa.table(
    "policies",
    sa.column("tenant_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.JSON),
    sa.column("updated_by", sa.String),
    sa.column("updated_at", sa.String),
)


def _json(raw: Any) -> Any:
    return json.loads(raw) if isinstance(raw, str) else raw


def _entry(
    tenant: str,
    team: str | None,
    target: str,
    *,
    before: Any,
    after: Any,
    at: str,
    teams: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    # A stored value may name a team since deleted; the entry then names it in its detail only.
    return {
        "id": new_id("aud"),
        "tenant_id": tenant,
        "team_id": team if team in teams else None,
        "actor": ACTOR,
        "action": "policy.reset",
        "target_kind": "policy",
        "target_id": target,
        "request_id": ACTOR[:64],
        "at": at,
        "detail": {"key": target, "team": team, "before": before, "after": after},
    }


def reset(c: sa.Connection) -> None:
    at = now_iso()
    stored = {
        t: _json(v)
        for t, v in c.execute(sa.text("SELECT tenant_id, value FROM policies WHERE key = :k"), {"k": KEY}).all()
    }
    floors = {
        t: _json(v)
        for t, v in c.execute(sa.text("SELECT tenant_id, value FROM policies WHERE key = :k"), {"k": FLOOR}).all()
    }
    teams = {t for (t,) in c.execute(sa.text("SELECT id FROM teams")).all()}
    audit: list[dict[str, Any]] = []
    for (tenant,) in c.execute(sa.text("SELECT id FROM tenants ORDER BY id")).all():
        raw = stored.get(tenant)
        # A plain true or false is a value stored before the key was per team: the workspace's own.
        value: dict[str, Any] = (
            dict(cast(dict[str, Any], raw)) if isinstance(raw, dict) else ({"*": raw} if isinstance(raw, bool) else {})
        )
        after = dict(value)
        for team, part in value.items():
            if part is not False:
                after[team] = False
                audit.append(
                    _entry(tenant, None if team == "*" else team, KEY, before=part, after=False, at=at, teams=teams)
                )
        if "*" not in value:
            after["*"] = False
            audit.append(_entry(tenant, None, KEY, before=None, after=False, at=at))
        if after != raw:
            row = {"value": after, "updated_by": ACTOR, "updated_at": at}
            if tenant in stored:
                c.execute(policies.update().where(policies.c.tenant_id == tenant, policies.c.key == KEY).values(**row))
            else:
                c.execute(policies.insert().values(tenant_id=tenant, key=KEY, **row))
        floor = floors.get(tenant)
        if isinstance(floor, dict) and KEY in floor:
            kept = {k: v for k, v in cast(dict[str, Any], floor).items() if k != KEY}
            c.execute(
                policies.update()
                .where(policies.c.tenant_id == tenant, policies.c.key == FLOOR)
                .values(value=kept, updated_by=ACTOR, updated_at=at)
            )
            audit.append(_entry(tenant, None, FLOOR, before=floor, after=kept, at=at))
    if audit:
        c.execute(audit_entries.insert(), audit)


def upgrade() -> None:
    reset(op.get_bind())


def downgrade() -> None:
    """Each value goes back from this revision's audit entries: a team's part, the workspace default (removed when
    the tenant stored none), and the floor as it was. The audit entries stay, since the audit log is append-only."""
    c = op.get_bind()
    rows = c.execute(
        sa.text("SELECT tenant_id, target_id, detail FROM audit_entries WHERE actor = :a"), {"a": ACTOR}
    ).all()
    for tenant in sorted({r[0] for r in rows}):
        mine = [(_json(d).get("team"), target, _json(d)) for t, target, d in rows if t == tenant]
        for _team, target, detail in mine:
            if target == FLOOR:
                c.execute(
                    policies.update()
                    .where(policies.c.tenant_id == tenant, policies.c.key == FLOOR)
                    .values(value=detail["before"])
                )
        current = c.execute(
            sa.text("SELECT value FROM policies WHERE tenant_id = :t AND key = :k"), {"t": tenant, "k": KEY}
        ).first()
        if current is None:
            continue
        value: dict[str, Any] = dict(_json(current[0]))
        for team, target, detail in mine:
            if target != KEY:
                continue
            slot = team or "*"
            if detail["before"] is None:
                value.pop(slot, None)
            else:
                value[slot] = detail["before"]
        if value:
            c.execute(
                policies.update().where(policies.c.tenant_id == tenant, policies.c.key == KEY).values(value=value)
            )
        else:
            c.execute(sa.text("DELETE FROM policies WHERE tenant_id = :t AND key = :k"), {"t": tenant, "k": KEY})
