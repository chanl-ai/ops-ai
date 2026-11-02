"""operation_body_encoding: an HTTP operation says how its body is sent, JSON, form or raw (c-591)

Bodies were JSON only, so a system that takes a form-encoded write, such as Stripe, could not be called from a REST
operation. Null keeps the JSON body every existing operation sends.

Revision ID: tools_0048_body_encoding
Revises: tools_0047_module_names
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0048_body_encoding"
down_revision = "tools_0047_module_names"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("body_encoding", sa.String(8)))


def downgrade() -> None:
    # deploy/database/tests/test_runtime_logins.py migrates the chain down past this revision and up again.
    op.drop_column("module_operations", "body_encoding")
