"""provisioned records carry a template id and a protection level (c-180)

Revision ID: tools_0021_template_protection
Revises: tools_0020_drop_security_reviews

Tool modules, egress hosts and ranges, and secrets gain `template_id` (the template slot a provisioned record fills,
indexed so the next run finds it) and `protection` (`system` or `managed`). Both are null on existing rows, so a record
from before reads as made by no template and unprotected.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0021_template_protection"
down_revision = "tools_0020_drop_security_reviews"
branch_labels = None
depends_on = None

TABLES = ("tool_modules", "egress_hosts", "egress_ranges", "tool_secrets")


def upgrade() -> None:
    for t in TABLES:
        op.add_column(t, sa.Column("template_id", sa.String(120), nullable=True))
        op.add_column(t, sa.Column("protection", sa.String(16), nullable=True))
        op.create_index(f"ix_{t}_template_id", t, ["template_id"])


def downgrade() -> None:
    for t in TABLES:
        op.drop_index(f"ix_{t}_template_id", table_name=t)
        op.drop_column(t, "protection")
        op.drop_column(t, "template_id")
