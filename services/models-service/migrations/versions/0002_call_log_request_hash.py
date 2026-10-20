"""call log request hash

Revision ID: models_0002
Revises: models_0001
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0002"
down_revision = "models_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The caller's hash of the request: ties a row to agents-service's model-call record and its replay key.
    op.add_column("model_call_log", sa.Column("request_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_model_call_log_thread_id", "model_call_log", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_model_call_log_thread_id", table_name="model_call_log")
    op.drop_column("model_call_log", "request_hash")
