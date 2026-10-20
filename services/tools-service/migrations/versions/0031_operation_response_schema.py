"""module_operations.response_schema: what an imported operation answers (c-353)

A workflow step's output fields were known only from a past run. An OpenAPI import now keeps the first success
response's JSON Schema on the operation, so a step that calls it shows its fields before it has run.

Revision ID: tools_0031_response_schema
Revises: tools_0030_call_channel
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "tools_0031_response_schema"
down_revision = "tools_0030_call_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("module_operations", sa.Column("response_schema", sa.JSON))


def downgrade() -> None:
    op.drop_column("module_operations", "response_schema")
