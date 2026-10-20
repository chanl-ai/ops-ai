"""one record per model call: usage_records and model_calls fold into model_call_records

Revision ID: 0020_model_call_records
Revises: 0019_publish_request_decisions

Usage rows move across unchanged. Recorded responses in model_calls are dropped, not copied: replay is now keyed by
the LangGraph task as well, which those rows do not have, so a run that crashed before the upgrade calls the model
once more when it is recovered.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_model_call_records"
down_revision = "0019_publish_request_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "model_call_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("step", sa.String(120), nullable=False),
        sa.Column("task", sa.String(200)),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("model_alias", sa.String(120), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("request_hash", sa.String(64)),
        sa.Column("response", sa.JSON()),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("thread_id", "task", "request_hash", name="uq_model_call_replay"),
    )
    op.create_index("ix_model_call_records_thread_id", "model_call_records", ["thread_id"])
    op.execute(
        "INSERT INTO model_call_records (id, thread_id, run_id, step, kind, model_alias, calls, input_tokens,"
        " output_tokens, cost_micros, created_at)"
        " SELECT id, thread_id, run_id, node, kind, model_alias, calls, input_tokens, output_tokens, cost_micros,"
        " created_at FROM usage_records"
    )
    op.drop_index("ix_usage_records_thread_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_table("model_calls")


def downgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "request_hash"),
    )
    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64)),
        sa.Column("node", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("model_alias", sa.String(120), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("cost_micros", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index("ix_usage_records_thread_id", "usage_records", ["thread_id"])
    op.execute(
        "INSERT INTO usage_records (id, thread_id, run_id, node, kind, model_alias, calls, input_tokens,"
        " output_tokens, cost_micros, created_at)"
        " SELECT id, thread_id, run_id, step, kind, model_alias, calls, input_tokens, output_tokens, cost_micros,"
        " created_at FROM model_call_records"
    )
    op.drop_index("ix_model_call_records_thread_id", table_name="model_call_records")
    op.drop_table("model_call_records")
