"""module approvals keep the requester's email (c-186)

Revision ID: tools_0022_requester_email
Revises: tools_0021_template_protection

The requester rule compares who decides with who asked by the token's email; the stored display name cannot be
compared. Existing approvals get null, which matches nobody.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0022_requester_email"
down_revision = "tools_0021_template_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_approvals", sa.Column("requested_by_email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("module_approvals", "requested_by_email")
