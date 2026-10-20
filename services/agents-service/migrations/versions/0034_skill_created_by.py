"""created_by on registry_skills: who created the skill, written once

Revision ID: 0034_skill_created_by
Revises: 0033_chat_search

Delete rights belong to the skill's creator or an admin of its team. Version 1's `saved_by` changes each time its
unpublished draft is saved, so it named the last saver, and a person who saved first could then delete (c-115). The
column is filled from version 1's `saved_by` for skills that already exist: the last person to save version 1, which
may not be its creator, and the best record kept.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0034_skill_created_by"
down_revision = "0033_chat_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("registry_skills") as b:
        b.add_column(sa.Column("created_by", sa.String(200), nullable=False, server_default=""))
    op.execute(
        "UPDATE registry_skills SET created_by = COALESCE((SELECT v.saved_by FROM registry_skill_versions v"
        " WHERE v.skill_id = registry_skills.id AND v.version = 1), '')"
    )


def downgrade() -> None:
    with op.batch_alter_table("registry_skills") as b:
        b.drop_column("created_by")
