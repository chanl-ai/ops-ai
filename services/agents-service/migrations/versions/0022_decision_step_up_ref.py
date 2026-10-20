"""step_up_ref on review_decisions: which re-authentication a money decision was made under

Revision ID: 0022_decision_step_up_ref
Revises: 0021_tenant_rls_run_tables

A fingerprint of the verified step-up (api/auth.py step_up_ref), so an auditor can tie a decision to the
re-authentication behind it without the token itself ever being stored. Null on decisions that needed none.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_decision_step_up_ref"
down_revision = "0021_tenant_rls_run_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_decisions") as b:
        b.add_column(sa.Column("step_up_ref", sa.String(40)))


def downgrade() -> None:
    with op.batch_alter_table("review_decisions") as b:
        b.drop_column("step_up_ref")
