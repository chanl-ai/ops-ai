"""agent changes: teams move to the new approvals default and keep only the policies a person saved

Agents now change apps without asking unless a team says otherwise (appChanges, appChangesByApp). A policy row exists
only where a person saved it, so each saved old policy is carried into the new keys: a team that set
toolWritesNeedApproval on asks a reviewer, apps listed in appWritesNeedApproval ask a reviewer, apps listed in
appsChangeWithoutAsking change without asking. Teams that saved nothing get no row and take the new default. The old
rows stay, as derived values for one release. The downgrade removes the new rows; the old ones still hold the meaning.

Revision ID: 0033_agent_changes_approvals
Revises: 0032_webhooks_usage_cells
"""

from __future__ import annotations

import json
from typing import cast

import sqlalchemy as sa
from alembic import op

revision = "0033_agent_changes_approvals"
down_revision = "0032_webhooks_usage_cells"
branch_labels = None
depends_on = None

NEW_KEYS = ("appChanges", "appChangesByApp")


def _value(raw: object) -> dict[str, object]:
    held: object = json.loads(raw) if isinstance(raw, str) else raw
    return cast(dict[str, object], held) if isinstance(held, dict) else {}


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT tenant_id, key, value, updated_by, updated_at FROM policies "
            "WHERE key IN ('toolWritesNeedApproval', 'appWritesNeedApproval', 'appsChangeWithoutAsking')"
        )
    ).all()
    changes: dict[str, dict[str, object]] = {}
    by_app: dict[str, dict[str, object]] = {}
    who: dict[str, tuple[object, object]] = {}
    for tenant, key, raw, by, at in rows:
        who[tenant] = (by, at)
        held = _value(raw)
        for team, listed in held.items():
            if key == "toolWritesNeedApproval" and listed is True:
                changes.setdefault(tenant, {})[team] = {
                    "ask": True,
                    "answer": "reviewer",
                    "reviewerRole": None,
                    "testAccountsNeverAsk": True,
                }
            elif key != "toolWritesNeedApproval" and isinstance(listed, list):
                answer = "reviewer" if key == "appWritesNeedApproval" else "none"
                for app in cast(list[object], listed):
                    by_app.setdefault(tenant, {}).setdefault(team, {})[str(app)] = {"answer": answer}  # type: ignore[index]
    for key, per_tenant in (("appChanges", changes), ("appChangesByApp", by_app)):
        for tenant, value in per_tenant.items():
            by, at = who[tenant]
            bind.execute(
                sa.text(
                    "INSERT INTO policies (tenant_id, key, value, updated_by, updated_at) "
                    "VALUES (:t, :k, cast(:v as json), :by, :at) ON CONFLICT (tenant_id, key) DO NOTHING"
                ),
                {"t": tenant, "k": key, "v": json.dumps(value), "by": by, "at": at},
            )


def downgrade() -> None:
    op.execute("DELETE FROM policies WHERE key IN ('appChanges', 'appChangesByApp')")
