"""published_loading on registry_skills: the published version's loading mode, so the skill picker filters in the query

Revision ID: 0042_skill_published_loading
Revises: 0041_engine_settings

The mode lived only in each version's content JSON, so the agent page's picker filtered always-on skills after the
page was read and returned short pages (c-136). Filled from each skill's published version.
"""

from __future__ import annotations

import json
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

revision = "0042_skill_published_loading"
down_revision = "0041_engine_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registry_skills") as b:
        b.add_column(sa.Column("published_loading", sa.String(16)))
    rows = op.get_bind().execute(
        sa.text(
            "SELECT s.id, v.content FROM registry_skills s JOIN registry_skill_versions v"
            " ON v.skill_id = s.id AND v.version = s.published_version"
        )
    )
    for skill_id, content in rows.all():
        parsed = cast(dict[str, Any], content if isinstance(content, dict) else json.loads(str(content)))
        loading = str(parsed.get("loading") or "on_match")
        op.execute(
            sa.text("UPDATE registry_skills SET published_loading = :l WHERE id = :i").bindparams(l=loading, i=skill_id)
        )


def downgrade() -> None:
    with op.batch_alter_table("registry_skills") as b:
        b.drop_column("published_loading")
