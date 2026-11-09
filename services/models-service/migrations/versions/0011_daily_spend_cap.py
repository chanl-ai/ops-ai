"""A model key may cap its spend per day

model_keys.daily_cap stops a key's calls once what the call log records it spent since midnight UTC reaches it: an
environment's ceiling on a service's background model work (kb-service's likely questions and FAQ drafts), apart
from the key's whole budget. Null is no daily cap. Runs on PostgreSQL and SQL Server.

Revision ID: models_0011
Revises: models_0010
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "models_0011"
down_revision = "models_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("model_keys", sa.Column("daily_cap", sa.Numeric(18, 6), nullable=True))
    op.create_index("ix_model_call_log_key_run", "model_call_log", ["key_id", "run_id"])


def downgrade() -> None:
    op.drop_index("ix_model_call_log_key_run", table_name="model_call_log")
    with op.batch_alter_table("model_keys") as b:
        b.drop_column("daily_cap")
