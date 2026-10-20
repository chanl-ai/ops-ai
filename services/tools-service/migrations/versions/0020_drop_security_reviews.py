"""tool module reviews live in agents-service's Reviews; the old table goes (c-163)

Revision ID: tools_0020_drop_security_reviews
Revises: tools_0019_version_reviews

tools-service copies every `security_reviews` row into Reviews at start-up (ops_tools.modules.review_copy) and deletes
each copied row. This migration refuses while any row is left, so no review is dropped before it reached Reviews: start
tools-service with agents-service up once, then migrate again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0020_drop_security_reviews"
down_revision = "tools_0019_version_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    left = op.get_bind().execute(sa.text("SELECT count(*) FROM security_reviews")).scalar_one()
    if left:
        raise RuntimeError(
            f"{left} tool module reviews are not in Reviews yet; start tools-service with agents-service up so it "
            "copies them, then migrate again."
        )
    op.drop_table("security_reviews")


def downgrade() -> None:
    op.create_table(
        "security_reviews",
        sa.Column("tenant_id", sa.String(64), primary_key=True),
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("module_id", sa.String(64), nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.Column("major", sa.Integer, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("requested_by", sa.String(200), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(200)),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("findings", sa.JSON, nullable=False),
        sa.Column("note", sa.Text),
        sa.ForeignKeyConstraint(
            ["tenant_id", "module_id"], ["tool_modules.tenant_id", "tool_modules.id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_security_reviews_module", "security_reviews", ["tenant_id", "module_id"], unique=False)
