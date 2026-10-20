"""registry_agents carry a template id and a protection level (c-180)

Revision ID: 0043_agent_template
Revises: 0042_skill_published_loading

The provisioning service (c-175) finds an agent again by the template it was made from, and marks it `system` (no
person may change it) or `managed` (people may; the template's fields come back on the next run). Both are null on
every agent made before, which reads as no template and no protection.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_agent_template"
down_revision = "0042_skill_published_loading"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("registry_agents", sa.Column("template_id", sa.String(120), nullable=True))
    op.add_column("registry_agents", sa.Column("protection", sa.String(16), nullable=True))
    op.create_index("ix_registry_agents_template_id", "registry_agents", ["template_id"])


def downgrade() -> None:
    op.drop_index("ix_registry_agents_template_id", table_name="registry_agents")
    op.drop_column("registry_agents", "protection")
    op.drop_column("registry_agents", "template_id")
